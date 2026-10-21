#!/usr/bin/env python3
"""既存プロジェクトへ「権限ポスチャ」を導入するスクリプト（新規インストール／旧L1版からの移行・冪等）。

使い方（このフレームワークの checkout から実行し、対象PJのパスを渡す）:
  python3 scripts/apply_posture.py /path/to/your-project [/path/to/another ...]
  python3 scripts/apply_posture.py --posture conservative /path/to/enterprise-project
  python3 scripts/apply_posture.py --set-user-default-mode auto /path/to/your-project
      # ↑ ~/.claude/settings.json の permissions.defaultMode を "auto" にする（opt-in・バックアップ作成）。
      #   auto mode は**プロジェクトの .claude/settings.json では有効化できない**（Claude Code 仕様）ため、
      #   「auto mode をデフォルトにする」にはユーザー設定か `claude --permission-mode auto` が必要。
  python3 scripts/apply_posture.py --install-auto-mode-rules      # 分類器ルール（templates/auto-mode-rules.json）を
  python3 scripts/apply_posture.py --remove-auto-mode-rules       #   ~/.claude/settings.json の autoMode にマージ／除去（opt-in）

非対称性（重要）: リポジトリは権限を**締める**ことはできるが**緩める**ことはできない。
  - `--posture conservative` → プロジェクト .claude/settings.json に permissions.defaultMode="default"（Manual）を書く。
    設定の優先順位は managed > CLI > プロジェクト > ユーザー なので、クローンした全員に Manual が強制される。
  - `--posture auto` → defaultMode は書かない（auto はプロジェクト設定では無効）。Claude Code の組み込み既定
    （ターミナルは auto）に乗る。本スクリプトが書いた "default" が残っていれば除去する。

やること:
  1. 新フック（policy / deny_guard / l1_shadow_log / permission_gate）と scripts/analyze_l1.py を配置
  2. honesty_check.py が無ければコピー（既にあり差分があれば**既存を保持**して報告）
  3. 旧 auto_approve.py を削除（permission_gate.py に置換）
  4. settings.json をマージ:
       - permissions.allow は**一切触らない**（育てた許可を消さない）
       - permissions.deny / ask はアプリ用フロアを union（不足分のみ追加・削除なし）
       - hooks は**温存マージ**: 本スクリプト管轄のフック配線だけ正規形に差し替え、
         導入者の独自フックは残す（消えるものがあれば必ず報告する＝loud）
  5. .orchestrator/permission_posture.json を作成（既定 auto。--posture で指定＝再合意。未指定なら既存を尊重）
  5b. ポスチャに合わせて permissions.defaultMode を同期（conservative="default" を書く／それ以外は除去）
  6. .gitignore にレシート保護を追記（無ければ）
  7. （--set-user-default-mode 指定時のみ）~/.claude/settings.json の permissions.defaultMode を更新
  8. （--install/--remove-auto-mode-rules 指定時のみ）~/.claude/settings.json の autoMode に
     フレームワーク推奨ルール（"[AI Orchestrator]" 接頭辞で識別・除去可能）をマージ／除去

コミットはしない。実行後に対象PJの diff を確認して人がコミットする。
詳細: docs/security/PERMISSION_POSTURE.md
"""
import json
import os
import shutil
import sys

# このスクリプト（<FW>/scripts/apply_posture.py）から見たフレームワーク root
FW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HOOK_FILES = ["policy.py", "deny_guard.py", "l1_shadow_log.py", "permission_gate.py"]
# 本スクリプトが配線を管理するフック（これ以外の既存フックは温存する）
MANAGED = set(HOOK_FILES + ["auto_approve.py", "honesty_check.py"])

# アプリPJ用の宣言的フロア（フレームワーク repo と違い .claude/** は全面書込禁止）
APP_DENY_FLOOR = [
    "Read(./.env)", "Read(./.env.*)", "Read(**/*.pem)", "Read(**/*.key)", "Read(**/*.p12)",
    "Read(**/id_rsa)", "Read(**/id_ed25519)", "Read(~/.ssh/**)", "Read(**/secrets/**)",
    "Read(**/credentials*.json)",
    "Write(./.env)", "Write(./.env.*)", "Edit(./.env)", "Edit(./.env.*)",
    "Write(.claude/**)", "Edit(.claude/**)", "Write(.git/hooks/**)", "Edit(.git/hooks/**)",
    "Bash(rm -rf *)", "Bash(rm -fr *)", "Bash(sudo *)",
    "Bash(git push --force *)", "Bash(git push -f *)",
    "Bash(curl * | bash)", "Bash(curl * | sh)", "Bash(wget * | bash)", "Bash(wget * | sh)",
]
APP_ASK = ["Bash(git push *)", "Bash(git reset --hard *)", "Bash(git rebase *)"]
VALID_POSTURES = ("auto", "conservative", "balanced", "permissive")
DEFAULT_POSTURE = "auto"  # Claude Code のネイティブ auto mode を正とする（CLAUDE.md Rule 9）
USER_SETTINGS = os.path.expanduser("~/.claude/settings.json")
AUTO_MODE_RULES = os.path.join(FW, "templates", "auto-mode-rules.json")
RULE_TAG = "[AI Orchestrator]"

RECEIPTS_GITIGNORE = """
# --- 権限ポスチャの観測レシート（コマンド列を含むためコミット禁止） ---
receipts/
**/l1-shadow.jsonl
**/l1-decisions.jsonl
"""


def _hook_cmd(name):
    return {"type": "command",
            "command": f'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/{name}"'}


def _is_managed(hook_entry):
    cmd = hook_entry.get("command", "")
    return any(f in cmd for f in MANAGED)


def _merge_hooks(hooks_cfg, log):
    """管轄フックの配線を正規形にし、導入者の独自フックは温存する。
    消える配線（旧 auto_approve 等）は必ず報告する（loud）。"""
    removed = []
    for ev in ("PreToolUse", "PostToolUse"):
        for g in hooks_cfg.get(ev, []):
            for h in g.get("hooks", []):
                if _is_managed(h):
                    removed.append(f"{ev}: {h.get('command', '')}")

    def _custom_groups(ev):
        out = []
        for g in hooks_cfg.get(ev, []):
            kept = [h for h in g.get("hooks", []) if not _is_managed(h)]
            if kept:
                out.append({"matcher": g.get("matcher", "*"), "hooks": kept})
        return out

    pre_custom = _custom_groups("PreToolUse")
    post_custom = _custom_groups("PostToolUse")

    hooks_cfg["PreToolUse"] = [{"matcher": "*", "hooks": [
        _hook_cmd("deny_guard.py"), _hook_cmd("permission_gate.py"), _hook_cmd("l1_shadow_log.py"),
    ]}] + pre_custom
    hooks_cfg["PostToolUse"] = [
        {"matcher": "*", "hooks": [_hook_cmd("l1_shadow_log.py")]},
        {"matcher": "Edit|Write|MultiEdit", "hooks": [_hook_cmd("honesty_check.py")]},
    ] + post_custom

    if removed:
        log.append("  hooks: 旧配線を正規形に差し替え（以下を置換）:")
        log.extend(f"    - {r}" for r in removed)
    n_custom = sum(len(g["hooks"]) for g in pre_custom + post_custom)
    if n_custom:
        log.append(f"  hooks: 導入者の独自フック {n_custom} 件を温存")


def apply(proj, posture=DEFAULT_POSTURE, posture_explicit=False):
    log = []
    proj = os.path.abspath(proj)
    if os.path.realpath(proj) == os.path.realpath(FW):
        # フレームワーク repo 自身には適用しない: フックは既に本体、settings.json のフロアは
        # 保守用に skills/agents を書ける狭い形（APP_DENY_FLOOR の .claude/** を入れると自己封鎖）。
        return [f"SKIP: {proj} はこのフレームワーク自身です。導入スクリプトは適用先プロジェクト専用。",
                "  この repo でポスチャを明示したいだけなら、.orchestrator/permission_posture.json に",
                f"  {{\"posture\": \"{posture}\"}} を直接書いてください（フックは次のツール呼び出しから読む）。",
                "  ファイルが無い場合もフックは何も自動承認せず、auto mode セッションでは分類器が決めます。"]
    claude_dir = os.path.join(proj, ".claude")
    if not os.path.isdir(claude_dir):
        return [f"SKIP: {proj} に .claude/ が無い（Claude Code プロジェクトではない？）"]
    hooks_dir = os.path.join(claude_dir, "hooks")
    os.makedirs(hooks_dir, exist_ok=True)

    # 1. 権限ポスチャのフック配置（常に最新へ更新）
    for f in HOOK_FILES:
        src, dst = os.path.join(FW, ".claude", "hooks", f), os.path.join(hooks_dir, f)
        before = open(dst, encoding="utf-8").read() if os.path.exists(dst) else None
        shutil.copy2(src, dst)  # copy2 は元ファイルのモードを保持（chmod 不要: フックは python3 で起動される）
        state = "新規" if before is None else ("更新" if before != open(dst, encoding="utf-8").read() else "同一")
        log.append(f"  hook {f}: {state}")

    # 2. honesty_check.py: 無ければコピー、既存差分は保持（勝手に上書きしない）
    hsrc, hdst = os.path.join(FW, ".claude", "hooks", "honesty_check.py"), os.path.join(hooks_dir, "honesty_check.py")
    if not os.path.exists(hdst):
        shutil.copy2(hsrc, hdst)
        log.append("  hook honesty_check.py: 新規")
    elif open(hdst, encoding="utf-8").read() != open(hsrc, encoding="utf-8").read():
        log.append("  hook honesty_check.py: 既存を保持（フレームワーク版と差分あり。必要なら手動更新）")
    else:
        log.append("  hook honesty_check.py: 同一")

    # 3. scripts/analyze_l1.py
    os.makedirs(os.path.join(proj, "scripts"), exist_ok=True)
    sdst = os.path.join(proj, "scripts", "analyze_l1.py")
    sb = open(sdst, encoding="utf-8").read() if os.path.exists(sdst) else None
    shutil.copy2(os.path.join(FW, "scripts", "analyze_l1.py"), sdst)
    log.append(f"  scripts/analyze_l1.py: {'新規' if sb is None else ('更新' if sb != open(sdst, encoding='utf-8').read() else '同一')}")

    # 4. 旧 auto_approve.py（permission_gate.py に置換済み）
    aa = os.path.join(hooks_dir, "auto_approve.py")
    if os.path.exists(aa):
        os.remove(aa)
        log.append("  auto_approve.py: 削除（permission_gate.py に置換）")

    # 5. settings.json マージ
    sp = os.path.join(claude_dir, "settings.json")
    d = json.load(open(sp, encoding="utf-8")) if os.path.exists(sp) else {}
    d.setdefault("$schema", "https://json.schemastore.org/claude-code-settings.json")
    perms = d.setdefault("permissions", {})
    allow_n = len(perms.get("allow", []))
    deny = perms.setdefault("deny", [])
    added_deny = [x for x in APP_DENY_FLOOR if x not in deny]
    deny.extend(added_deny)
    ask = perms.setdefault("ask", [])
    added_ask = [x for x in APP_ASK if x not in ask]
    ask.extend(added_ask)
    _merge_hooks(d.setdefault("hooks", {}), log)
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
        f.write("\n")
    log.append(f"  settings.json: allow {allow_n}件 温存 / deny +{len(added_deny)} / ask +{len(added_ask)}")

    # 6. posture（既定 auto）。--posture 明示＝再合意として上書き。未指定なら既存を尊重（引き継ぎ）
    orch = os.path.join(proj, ".orchestrator")
    os.makedirs(orch, exist_ok=True)
    pj = os.path.join(orch, "permission_posture.json")
    effective = posture
    if os.path.exists(pj) and not posture_explicit:
        try:
            cur = json.load(open(pj, encoding="utf-8")).get("posture")
        except Exception:
            cur = None
        if cur in VALID_POSTURES:
            effective = cur
            log.append(f"  permission_posture.json: 既存を尊重（{cur}）")
        else:
            log.append(f"  ⚠ permission_posture.json: 読取不能/不正値（{cur!r}）→ {posture} で書き直し")
            effective = posture
            with open(pj, "w", encoding="utf-8") as f:
                json.dump({"posture": posture}, f, indent=2)
                f.write("\n")
    else:
        with open(pj, "w", encoding="utf-8") as f:
            json.dump({"posture": posture}, f, indent=2)
            f.write("\n")
        log.append(f"  permission_posture.json: {'再合意で更新' if os.path.exists(pj) and posture_explicit else '新規作成'} {posture}"
                   "（起動時の作業合意インタビューで変更可）")

    # 6b. defaultMode の同期 — リポジトリは「締める」ことだけできる
    dm = perms.get("defaultMode")
    if dm in ("auto", "bypassPermissions"):
        log.append(f"  ⚠ settings.json の permissions.defaultMode='{dm}' はプロジェクト設定では無効です"
                   "（ユーザー設定の defaultMode も無視されます）。除去して ~/.claude/settings.json に移してください")
        perms.pop("defaultMode", None)
        log.append("  settings.json: 無効な defaultMode を除去しました")
    if effective == "conservative":
        if dm != "default":
            perms["defaultMode"] = "default"
            log.append("  settings.json: permissions.defaultMode=\"default\"（Manual）を設定 — クローンした全員に強制される"
                       "（CLI フラグと managed settings だけがこれを上書きできる）")
        else:
            log.append("  settings.json: defaultMode=default 既存（conservative と整合）")
    elif dm == "default":
        perms.pop("defaultMode", None)
        log.append(f"  settings.json: defaultMode=\"default\" を除去（ポスチャ {effective} は Claude Code の既定モードに乗る）")
    if effective == "auto":
        log.append("  ※ auto ポスチャは Claude Code の auto mode を正とする。auto mode 自体はプロジェクト設定では"
                   "有効化できないため、起動時に auto mode でなければフックは conservative 相当で動き、その旨を表示する")
    # settings.json を書き直す（6b で変更があり得るため最終形で保存）
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
        f.write("\n")

    # 7. .gitignore レシート保護
    gi = os.path.join(proj, ".gitignore")
    txt = open(gi, encoding="utf-8").read() if os.path.exists(gi) else ""
    if "l1-shadow.jsonl" not in txt:
        with open(gi, "a", encoding="utf-8") as f:
            f.write(RECEIPTS_GITIGNORE)
        log.append("  .gitignore: レシート保護を追記")
    else:
        log.append("  .gitignore: レシート保護 既存")
    return log


def set_user_default_mode(mode):
    """~/.claude/settings.json の permissions.defaultMode を更新する（opt-in・バックアップ・温存マージ）。
    auto mode は ~/.claude/settings.json（または managed settings / --permission-mode）でしか既定化できない。"""
    d = {}
    if os.path.exists(USER_SETTINGS):
        try:
            d = json.load(open(USER_SETTINGS, encoding="utf-8")) or {}
        except Exception as e:
            print(f"ERROR: {USER_SETTINGS} を読めません（{e.__class__.__name__}）。手で確認してください", file=sys.stderr)
            sys.exit(1)
        shutil.copy2(USER_SETTINGS, USER_SETTINGS + ".bak")
    perms = d.setdefault("permissions", {})
    before = perms.get("defaultMode")
    perms["defaultMode"] = mode
    os.makedirs(os.path.dirname(USER_SETTINGS), exist_ok=True)
    with open(USER_SETTINGS, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\n~/.claude/settings.json: permissions.defaultMode {before!r} → {mode!r}"
          + ("（バックアップ: settings.json.bak）" if before is not None or os.path.exists(USER_SETTINGS + ".bak") else ""))
    if mode == "auto":
        print("  auto mode が利用できない環境（旧バージョン・disableAutoMode・非対応モデル）では Manual で起動します。"
              "起動後に `/permissions` またはステータス行でモードを確認してください。")


def _load_user_settings():
    d = {}
    if os.path.exists(USER_SETTINGS):
        try:
            d = json.load(open(USER_SETTINGS, encoding="utf-8")) or {}
        except Exception as e:
            print(f"ERROR: {USER_SETTINGS} を読めません（{e.__class__.__name__}）。手で確認してください", file=sys.stderr)
            sys.exit(1)
        shutil.copy2(USER_SETTINGS, USER_SETTINGS + ".bak")
    return d


def _save_user_settings(d):
    os.makedirs(os.path.dirname(USER_SETTINGS), exist_ok=True)
    with open(USER_SETTINGS, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
        f.write("\n")


def install_auto_mode_rules():
    """templates/auto-mode-rules.json の autoMode ルールを ~/.claude/settings.json にマージする（opt-in・冪等・温存）。
    - 利用者の既存エントリは消さない。本スクリプトのルールは RULE_TAG 接頭辞で識別する（--remove で除去可能）。
    - 利用者のリストに "$defaults" が無い（＝組み込みルールを意図的に置換している）場合は足さずに警告する。
    - autoMode ルールはユーザー設定/managed settings にしか置けない（プロジェクト設定では読まれない）。"""
    tpl = json.load(open(AUTO_MODE_RULES, encoding="utf-8")).get("autoMode", {})
    d = _load_user_settings()
    am = d.setdefault("autoMode", {})
    added, kept, warn = 0, 0, []
    for section, rules in tpl.items():
        ours = [r for r in rules if r != "$defaults"]
        if not all(r.startswith(RULE_TAG) for r in ours):
            print(f"ERROR: テンプレート {section} に {RULE_TAG} 接頭辞の無いルールがあります（識別不能になるため中止）", file=sys.stderr)
            sys.exit(1)
        if section not in am:
            am[section] = list(rules)  # "$defaults" を含めて丸ごと
            added += len(ours)
            continue
        cur = am[section]
        if "$defaults" not in cur:
            warn.append(f"autoMode.{section} に \"$defaults\" が無い（組み込みルールを置換中）。足していません。意図的でなければ先頭に追加してください")
        for r in ours:
            if r in cur:
                kept += 1
            else:
                cur.append(r)
                added += 1
    _save_user_settings(d)
    print(f"\n~/.claude/settings.json: autoMode ルール 追加 {added} / 既存 {kept}（バックアップ: settings.json.bak）")
    for w in warn:
        print(f"  ⚠ {w}")
    print("  反映確認: `claude auto-mode config`（有効なルール一覧）。ルールは散文で確定的ではないため、deny フロアの代替にはならない。")
    print("  このルールは**あなたの全プロジェクト**に効く。不要になったら --remove-auto-mode-rules で除去できる。")


def remove_auto_mode_rules():
    d = _load_user_settings()
    am = d.get("autoMode", {})
    removed = 0
    for section in list(am.keys()):
        if isinstance(am[section], list):
            before = len(am[section])
            am[section] = [r for r in am[section] if not (isinstance(r, str) and r.startswith(RULE_TAG))]
            removed += before - len(am[section])
            if am[section] == ["$defaults"] or not am[section]:
                del am[section]  # 組み込みのみ＝未設定と同じ
    if not am:
        d.pop("autoMode", None)
    _save_user_settings(d)
    print(f"\n~/.claude/settings.json: {RULE_TAG} ルールを {removed} 件除去（利用者の独自ルールは温存）")


def main():
    args = sys.argv[1:]
    posture, user_mode, targets = DEFAULT_POSTURE, None, []
    posture_explicit, install_rules, remove_rules = False, False, False
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--posture":
            i += 1
            posture = args[i] if i < len(args) else ""
            posture_explicit = True
            if posture not in VALID_POSTURES:
                print(f"ERROR: --posture は {VALID_POSTURES} のいずれか（{posture!r}）", file=sys.stderr)
                sys.exit(1)
        elif a == "--set-user-default-mode":
            i += 1
            user_mode = args[i] if i < len(args) else ""
            if user_mode not in ("auto", "default", "acceptEdits", "plan"):
                print(f"ERROR: --set-user-default-mode は auto / default / acceptEdits / plan（{user_mode!r}）", file=sys.stderr)
                sys.exit(1)
        elif a == "--install-auto-mode-rules":
            install_rules = True
        elif a == "--remove-auto-mode-rules":
            remove_rules = True
        else:
            targets.append(a)
        i += 1
    if not targets and not user_mode and not install_rules and not remove_rules:
        print(__doc__)
        sys.exit(1)
    for proj in targets:
        print(f"\n########## {proj} ##########")
        for line in apply(proj, posture, posture_explicit):
            print(line)
    if user_mode:
        set_user_default_mode(user_mode)
    if remove_rules:
        remove_auto_mode_rules()
    if install_rules:
        install_auto_mode_rules()
    print("\n完了（コミットはしていません）。対象PJの diff を確認してからコミットしてください。")
    print("フック配線の変更は settings.json の再読込（多くはセッション再起動）で反映されます。")


if __name__ == "__main__":
    main()
