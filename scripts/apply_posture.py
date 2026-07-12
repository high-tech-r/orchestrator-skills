#!/usr/bin/env python3
"""既存プロジェクトへ「権限ポスチャ」を導入するスクリプト（新規インストール／旧L1版からの移行・冪等）。

使い方（このフレームワークの checkout から実行し、対象PJのパスを渡す）:
  python3 scripts/apply_posture.py /path/to/your-project [/path/to/another ...]

やること:
  1. 新フック（policy / deny_guard / l1_shadow_log / permission_gate）と scripts/analyze_l1.py を配置
  2. honesty_check.py が無ければコピー（既にあり差分があれば**既存を保持**して報告）
  3. 旧 auto_approve.py を削除（permission_gate.py に置換）
  4. settings.json をマージ:
       - permissions.allow は**一切触らない**（育てた許可を消さない）
       - permissions.deny / ask はアプリ用フロアを union（不足分のみ追加・削除なし）
       - hooks は**温存マージ**: 本スクリプト管轄のフック配線だけ正規形に差し替え、
         導入者の独自フックは残す（消えるものがあれば必ず報告する＝loud）
  5. .orchestrator/permission_posture.json を conservative で作成（既存があれば尊重）
  6. .gitignore にレシート保護を追記（無ければ）

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


def apply(proj):
    log = []
    proj = os.path.abspath(proj)
    claude_dir = os.path.join(proj, ".claude")
    if not os.path.isdir(claude_dir):
        return [f"SKIP: {proj} に .claude/ が無い（Claude Code プロジェクトではない？）"]
    hooks_dir = os.path.join(claude_dir, "hooks")
    os.makedirs(hooks_dir, exist_ok=True)

    # 1. 権限ポスチャのフック配置（常に最新へ更新）
    for f in HOOK_FILES:
        src, dst = os.path.join(FW, ".claude", "hooks", f), os.path.join(hooks_dir, f)
        before = open(dst, encoding="utf-8").read() if os.path.exists(dst) else None
        shutil.copy2(src, dst)
        os.chmod(dst, 0o755)
        state = "新規" if before is None else ("更新" if before != open(dst, encoding="utf-8").read() else "同一")
        log.append(f"  hook {f}: {state}")

    # 2. honesty_check.py: 無ければコピー、既存差分は保持（勝手に上書きしない）
    hsrc, hdst = os.path.join(FW, ".claude", "hooks", "honesty_check.py"), os.path.join(hooks_dir, "honesty_check.py")
    if not os.path.exists(hdst):
        shutil.copy2(hsrc, hdst)
        os.chmod(hdst, 0o755)
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
    os.chmod(sdst, 0o755)
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

    # 6. posture 既定 conservative（既存があれば尊重＝引き継ぎ）
    orch = os.path.join(proj, ".orchestrator")
    os.makedirs(orch, exist_ok=True)
    pj = os.path.join(orch, "permission_posture.json")
    if os.path.exists(pj):
        try:
            cur = json.load(open(pj, encoding="utf-8")).get("posture")
        except Exception:
            cur = "（読取不能）"
        log.append(f"  permission_posture.json: 既存を尊重（{cur}）")
    else:
        with open(pj, "w", encoding="utf-8") as f:
            json.dump({"posture": "conservative"}, f, indent=2)
            f.write("\n")
        log.append("  permission_posture.json: 新規作成 conservative（起動時の作業合意インタビューで変更可）")

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


def main():
    targets = sys.argv[1:]
    if not targets:
        print(__doc__)
        sys.exit(1)
    for proj in targets:
        print(f"\n########## {proj} ##########")
        for line in apply(proj):
            print(line)
    print("\n完了（コミットはしていません）。対象PJの diff を確認してからコミットしてください。")
    print("フック配線の変更は settings.json の再読込（多くはセッション再起動）で反映されます。")


if __name__ == "__main__":
    main()
