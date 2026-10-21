#!/usr/bin/env python3
"""権限ポスチャ一式の検証ハーネス（保守者向け・ライブ Claude Code セッション不要）。

合成した PreToolUse JSON を stdin からフックに流し、決定表どおりに動くかを検証する:
  A. permission_gate の決定表（conservative/balanced/permissive × floor/可逆/その他）
  A1. auto ポスチャ／auto mode セッションの挙動（分類器に委ねる・floor 常時ON・不一致を loud）
  A2. 壊れた config → conservative フォールバック＋loud（stderr 警告）
  B. ポスチャ切替スモーク（config ファイル経由）＋ deny フロア常時ON
  B2. deny_guard 単独（floor → exit2 / それ以外 → exit0）
  C. analyze_l1 E2E（レシート → allow-list 候補）
  D. redact（レシートに秘密が平文で残らない）
  E. settings.json 健全性（配線順・ask/deny）
  F. 自己権限フロアの限定（settings/hooks はブロック・skills/agents は許可）
  G. apply_posture.py（既存PJ導入スクリプト: 独自フック/allow 温存・冪等・conservative の Manual 強制）
  H. autoMode 分類器ルールの導入/除去（HOME 差し替え・温存・冪等）

実行: python3 scripts/verify_permission_hooks.py   （終了コード 0=全PASS / 1=失敗あり）
      ORCH_HOOKS_DIR=/path/to/staged/hooks python3 scripts/verify_permission_hooks.py
      （.claude/hooks/ は deny フロアで AI が書けないため、差し替え前のフック一式を別ディレクトリで検証できる）
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.environ.get("ORCH_HOOKS_DIR") or os.path.join(ROOT, ".claude", "hooks")
GATE = os.path.join(HOOKS, "permission_gate.py")
DENY = os.path.join(HOOKS, "deny_guard.py")
SHADOW = os.path.join(HOOKS, "l1_shadow_log.py")
ANALYZE = os.path.join(ROOT, "scripts", "analyze_l1.py")
APPLY = os.path.join(ROOT, "scripts", "apply_posture.py")

passed = 0
failed = 0


def run(script, payload, env=None, extra_env=None):
    e = dict(os.environ) if env is None else dict(env)
    if extra_env:
        e.update(extra_env)
    p = subprocess.run([sys.executable, script], input=json.dumps(payload),
                       capture_output=True, text=True, env=e)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def decision_of(stdout):
    """hookSpecificOutput.permissionDecision を返す。decision 無し（systemMessage のみ等）は None。"""
    if not stdout:
        return None
    try:
        return (json.loads(stdout).get("hookSpecificOutput") or {}).get("permissionDecision")
    except Exception:
        return f"UNPARSEABLE:{stdout!r}"


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}")


def bash(cmd):
    return {"tool_name": "Bash", "tool_input": {"command": cmd},
            "tool_use_id": "t1", "session_id": "s1", "hook_event_name": "PreToolUse"}


def readtool(path):
    return {"tool_name": "Read", "tool_input": {"file_path": path},
            "tool_use_id": "t2", "session_id": "s1", "hook_event_name": "PreToolUse"}


print("=== A. permission_gate 決定表（ORCH_POSTURE 指定）===")
cases = [
    ("conservative", bash("rm -rf /tmp/x"), "deny", 2, "any/rm -rf -> deny"),
    ("balanced",     bash("foo && sudo rm x"), "deny", 2, "any/sudo -> deny"),
    ("conservative", bash("ls -la"), None, 0, "conservative/ls -> prompt(no stdout)"),
    ("conservative", readtool("src/a.py"), None, 0, "conservative/Read -> prompt(no stdout)"),
    ("balanced",     bash("ls -la"), "allow", 0, "balanced/ls -> allow"),
    ("balanced",     readtool("src/a.py"), "allow", 0, "balanced/Read -> allow"),
    ("balanced",     bash("npm publish"), "deny", 2, "balanced/npm publish -> deny(floor)"),
    ("balanced",     bash("psql -c 'select 1'"), None, 0, "balanced/psql -> prompt(no stdout)"),
    ("permissive",   bash("psql -c 'select 1'"), "allow", 0, "permissive/psql -> allow"),
    ("permissive",   bash("git push --force origin main"), "deny", 2, "permissive/force push -> deny(floor)"),
]
tmp_rcpt = tempfile.mkdtemp(prefix="l1test_")
for posture, payload, exp_dec, exp_exit, label in cases:
    rc, out, err = run(GATE, payload, extra_env={"ORCH_POSTURE": posture,
                                                 "L1_RECEIPTS_DIR": tmp_rcpt})
    dec = decision_of(out)
    check(f"{label}  (exit={rc}, dec={dec})", dec == exp_dec and rc == exp_exit)

print("\n=== A1. auto ポスチャ / auto mode セッション ===")


def with_mode(payload, mode, sid="s-a1"):
    p = dict(payload)
    p["permission_mode"] = mode
    p["session_id"] = sid
    return p


def sysmsg_of(stdout):
    if not stdout:
        return None
    try:
        return json.loads(stdout).get("systemMessage")
    except Exception:
        return None


a1_rcpt = tempfile.mkdtemp(prefix="l1a1_")
E = {"L1_RECEIPTS_DIR": a1_rcpt}
# auto ポスチャ × auto mode: allow を出さない（分類器に委ねる）／floor は deny
rc, out, _ = run(GATE, with_mode(bash("psql -c 'select 1'"), "auto"), extra_env=dict(E, ORCH_POSTURE="auto"))
check(f"auto/auto-mode: psql -> no decision (classifier decides) (dec={decision_of(out)})", decision_of(out) is None and rc == 0)
rc, out, _ = run(GATE, with_mode(bash("rm -rf /tmp/x"), "auto"), extra_env=dict(E, ORCH_POSTURE="auto"))
check("auto/auto-mode: 再帰強制削除 -> deny (floor holds in auto mode)", decision_of(out) == "deny" and rc == 2)
# auto ポスチャ × auto mode でない: allow を出さず、初回だけ systemMessage で loud
rc, out, _ = run(GATE, with_mode(bash("ls"), "default", "s-a1-mismatch"), extra_env=dict(E, ORCH_POSTURE="auto"))
check(f"auto/default-mode: ls -> no allow (conservative相当) (dec={decision_of(out)})", decision_of(out) is None and rc == 0)
check("auto/default-mode: 初回は systemMessage で不一致を通知（loud）", bool(sysmsg_of(out)) and "auto" in sysmsg_of(out))
rc, out2, _ = run(GATE, with_mode(bash("ls"), "default", "s-a1-mismatch"), extra_env=dict(E, ORCH_POSTURE="auto"))
check("auto/default-mode: 2回目は通知しない（once per session）", not out2)
# balanced/permissive × auto mode: フックは allow を出さず分類器に委ねる＋初回通知
rc, out, _ = run(GATE, with_mode(bash("ls"), "auto", "s-a1-bal"), extra_env=dict(E, ORCH_POSTURE="balanced"))
check(f"balanced/auto-mode: ls -> no allow (defer to classifier) (dec={decision_of(out)})", decision_of(out) is None and rc == 0)
check("balanced/auto-mode: 初回に委譲を通知", bool(sysmsg_of(out)) and "auto" in sysmsg_of(out))
rc, out, _ = run(GATE, with_mode(bash("psql -c x"), "auto", "s-a1-perm"), extra_env=dict(E, ORCH_POSTURE="permissive"))
check(f"permissive/auto-mode: psql -> no allow (defer to classifier) (dec={decision_of(out)})", decision_of(out) is None and rc == 0)
# conservative × auto mode（CLI フラグ等でプロジェクト設定を上書きされた）: allow は出さず初回通知
rc, out, _ = run(GATE, with_mode(bash("psql -c x"), "auto", "s-a1-cons"), extra_env=dict(E, ORCH_POSTURE="conservative"))
check(f"conservative/auto-mode: psql -> no allow (dec={decision_of(out)})", decision_of(out) is None and rc == 0)
check("conservative/auto-mode: 初回に『auto mode で動いている』と通知", bool(sysmsg_of(out)) and "auto" in sysmsg_of(out))
# posture ファイル無し × auto mode: 既定フォールバックは「選ばれた conservative」ではないので通知しない（誤警報防止）
nf = tempfile.mkdtemp(prefix="l1nofile_")
os.makedirs(os.path.join(nf, ".orchestrator"))
nfenv = {k: v for k, v in os.environ.items() if k != "ORCH_POSTURE"}
nfenv.update(CLAUDE_PROJECT_DIR=nf, L1_RECEIPTS_DIR=a1_rcpt)
rc, out, _ = run(GATE, with_mode(bash("psql -c x"), "auto", "s-a1-nofile"), env=nfenv)
check("no-file/auto-mode: 出力なし（conservative 通知の誤警報を出さない）", not out and rc == 0)
# 旧バージョン（permission_mode 無し）× auto ポスチャ: 静かに conservative 相当
rc, out, _ = run(GATE, bash("ls"), extra_env=dict(E, ORCH_POSTURE="auto"))
check("auto/no-mode-field: ls -> no decision, no notice", not out and rc == 0)
# balanced × 非 auto mode は従来どおり allow
rc, out, _ = run(GATE, with_mode(bash("ls"), "default"), extra_env=dict(E, ORCH_POSTURE="balanced"))
check(f"balanced/default-mode: ls -> allow (従来挙動) (dec={decision_of(out)})", decision_of(out) == "allow")
# レシートに permission_mode が記録される
rec_txt = ""
for root_, _, files in os.walk(a1_rcpt):
    for fn in files:
        if fn == "l1-decisions.jsonl":
            rec_txt += open(os.path.join(root_, fn)).read()
check("receipt: permission_mode と decision=classifier が記録される", '"permission_mode": "auto"' in rec_txt and '"classifier"' in rec_txt)

print("\n=== A2. 壊れた config -> conservative フォールバック + loud ===")
bad_dir = tempfile.mkdtemp(prefix="l1bad_")
os.makedirs(os.path.join(bad_dir, ".orchestrator"))
with open(os.path.join(bad_dir, ".orchestrator", "permission_posture.json"), "w") as f:
    f.write("{garbage not json")
env = {k: v for k, v in os.environ.items() if k != "ORCH_POSTURE"}
env["CLAUDE_PROJECT_DIR"] = bad_dir
env["L1_RECEIPTS_DIR"] = tmp_rcpt
rc, out, err = run(GATE, bash("ls -la"), env=env)
check(f"壊れconfig: ls -> prompt(no decision) (dec={decision_of(out)})", decision_of(out) is None and rc == 0)
check("壊れconfig: stderr に⚠警告 (loud)", "⚠" in err and "conservative" in err)
rc2, out2, _ = run(GATE, bash("rm -rf /"), env=env)
check("壊れconfig: rm -rf は依然 deny", decision_of(out2) == "deny" and rc2 == 2)

print("\n=== B. ポスチャ切替スモーク（config ファイル経由・env なし）===")
proj = tempfile.mkdtemp(prefix="l1proj_")
os.makedirs(os.path.join(proj, ".orchestrator"))
pfile = os.path.join(proj, ".orchestrator", "permission_posture.json")
benv = {k: v for k, v in os.environ.items() if k != "ORCH_POSTURE"}
benv["CLAUDE_PROJECT_DIR"] = proj
benv["L1_RECEIPTS_DIR"] = tmp_rcpt
expect_ls = {"auto": None, "conservative": None, "balanced": "allow", "permissive": "allow"}
for posture in ("auto", "conservative", "balanced", "permissive"):
    with open(pfile, "w") as f:
        json.dump({"posture": posture}, f)
    rc, out, _ = run(GATE, bash("ls"), env=benv)
    check(f"file={posture}: ls -> {expect_ls[posture]} (got {decision_of(out)})",
          decision_of(out) == expect_ls[posture])
    rc2, out2, _ = run(GATE, bash("rm -rf /"), env=benv)
    check(f"file={posture}: rm -rf -> deny (floor always on)", decision_of(out2) == "deny" and rc2 == 2)

print("\n=== B2. deny_guard 単独（floor -> exit2 / それ以外 -> exit0）===")
rc, out, _ = run(DENY, bash("rm -rf /tmp/x"))
check("deny_guard rm -rf -> deny/exit2", decision_of(out) == "deny" and rc == 2)
rc, out, _ = run(DENY, bash("ls -la"))
check("deny_guard ls -> no decision/exit0", out == "" and rc == 0)

print("\n=== C. analyze_l1 E2E ===")
rc_dir = tempfile.mkdtemp(prefix="l1rcpt_")
day = "2026-01-01"
os.makedirs(os.path.join(rc_dir, day))
recs = []
for i in range(6):  # 可逆ファミリー: 6回 intended, 全て executed
    tid = f"gs{i}"
    recs.append({"event": "PreToolUse", "key": "Bash: git status", "tool_use_id": tid,
                 "verdict": "auto", "tool": "Bash", "raw": "git status"})
    recs.append({"event": "PostToolUse", "key": "Bash: git status", "tool_use_id": tid})
for i in range(6):  # ask ファミリー: 昇格してはいけない
    tid = f"psql{i}"
    recs.append({"event": "PreToolUse", "key": "Bash: psql", "tool_use_id": tid,
                 "verdict": "ask", "tool": "Bash", "raw": "psql -c x"})
    recs.append({"event": "PostToolUse", "key": "Bash: psql", "tool_use_id": tid})
with open(os.path.join(rc_dir, day, "l1-shadow.jsonl"), "w") as f:
    for r in recs:
        f.write(json.dumps(r) + "\n")
p = subprocess.run([sys.executable, ANALYZE, "--receipts", rc_dir, "--min", "5"],
                   capture_output=True, text=True)
check("analyze: git status が allow 候補に出る", "Bash(git status *)" in p.stdout)
check("analyze: psql(ask系) は候補に出ない", "Bash(psql *)" not in p.stdout)

print("\n=== D. redact（レシートにトークンが平文で残らない）===")
d_rcpt = tempfile.mkdtemp(prefix="l1redact_")
secret_cmd = "curl -H 'Authorization: Bearer sk-secret123ABCDEF' https://api.example.com"
run(SHADOW, {"tool_name": "Bash", "tool_input": {"command": secret_cmd},
             "tool_use_id": "r1", "session_id": "s1", "hook_event_name": "PreToolUse"},
    extra_env={"L1_RECEIPTS_DIR": d_rcpt})
found_secret, receipt_text = False, ""
for root, _, files in os.walk(d_rcpt):
    for fn in files:
        if fn == "l1-shadow.jsonl":
            receipt_text = open(os.path.join(root, fn)).read()
            if "sk-secret123ABCDEF" in receipt_text:
                found_secret = True
check("redact: raw secret がレシートに存在しない", not found_secret and receipt_text != "")
check("redact: マスク跡(***)がある", "***" in receipt_text)

print("\n=== E. settings.json 健全性 ===")
d = json.load(open(os.path.join(ROOT, ".claude", "settings.json")))
pre = [h["command"].split("/")[-1].rstrip('"') for h in d["hooks"]["PreToolUse"][0]["hooks"]]
check(f"PreToolUse 順序 = deny_guard,permission_gate,l1_shadow_log  (got {pre})",
      pre == ["deny_guard.py", "permission_gate.py", "l1_shadow_log.py"])
check("ask に git push がある", any("git push" in x for x in d["permissions"].get("ask", [])))
deny_rules = d["permissions"]["deny"]
check("deny は特権ファイル限定（settings.json + hooks）",
      "Write(.claude/settings.json)" in deny_rules and "Write(.claude/hooks/**)" in deny_rules)
check("deny に広すぎる .claude/** が無い（skills/agents を殺さない）",
      "Write(.claude/**)" not in deny_rules and "Edit(.claude/**)" not in deny_rules)
check("settings.json に defaultMode=auto/bypass を書いていない（プロジェクト設定では無効＝偽の既定化を防ぐ）",
      d["permissions"].get("defaultMode") not in ("auto", "bypassPermissions"))

print("\n=== F. 自己権限フロアの限定（policy.match_deny）===")
sys.path.insert(0, HOOKS)
from policy import match_deny  # noqa: E402


def w(p):
    return match_deny("Write", {"file_path": p})


check("settings.json 書込 -> ブロック", w(".claude/settings.json") is not None)
check("hooks/ 書込 -> ブロック", w(".claude/hooks/policy.py") is not None)
check(".git/hooks/ 書込 -> ブロック", w(".git/hooks/pre-commit") is not None)
check("skills/ 書込 -> 許可（None）", w(".claude/skills/orchestrate/SKILL.md") is None)
check("agents/ 書込 -> 許可（None）", w(".claude/agents/honesty-auditor.md") is None)
check(".env 書込 -> ブロック", w("app/.env") is not None)

print("\n=== G. apply_posture.py（既存PJ導入・温存マージ・冪等）===")
tgt = tempfile.mkdtemp(prefix="l1apply_")
os.makedirs(os.path.join(tgt, ".claude", "hooks"))
# 既存PJを模擬: 育てた allow・独自フック・旧 auto_approve 配線・旧フック実体
fake_settings = {
    "permissions": {"allow": ["Bash(php artisan *)", "Bash(docker compose *)"],
                    "deny": ["Read(./.env)"]},
    "hooks": {
        "PreToolUse": [{"matcher": "*", "hooks": [
            {"type": "command", "command": 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/auto_approve.py"'},
            {"type": "command", "command": 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/my_custom.py"'},
        ]}],
        "PostToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/my_post.py"'},
        ]}],
    },
}
with open(os.path.join(tgt, ".claude", "settings.json"), "w") as f:
    json.dump(fake_settings, f)
open(os.path.join(tgt, ".claude", "hooks", "auto_approve.py"), "w").write("# old\n")

p1 = subprocess.run([sys.executable, APPLY, tgt], capture_output=True, text=True)
d1 = json.load(open(os.path.join(tgt, ".claude", "settings.json")))
pre1 = [h["command"] for g in d1["hooks"]["PreToolUse"] for h in g["hooks"]]
post1 = [h["command"] for g in d1["hooks"]["PostToolUse"] for h in g["hooks"]]
check("apply: 実行成功(exit0)", p1.returncode == 0)
check("apply: allow 温存", d1["permissions"]["allow"] == fake_settings["permissions"]["allow"])
check("apply: 独自 Pre フック温存", any("my_custom.py" in c for c in pre1))
check("apply: 独自 Post フック温存", any("my_post.py" in c for c in post1))
check("apply: auto_approve 配線が消える", not any("auto_approve" in c for c in pre1 + post1))
check("apply: auto_approve 実体が消える",
      not os.path.exists(os.path.join(tgt, ".claude", "hooks", "auto_approve.py")))
check("apply: 新3フック配線（先頭グループ・順序）",
      [c.split("/")[-1].rstrip('"') for c in pre1[:3]] == ["deny_guard.py", "permission_gate.py", "l1_shadow_log.py"])
check("apply: honesty_check が新規コピーされる",
      os.path.exists(os.path.join(tgt, ".claude", "hooks", "honesty_check.py")))
pj1 = json.load(open(os.path.join(tgt, ".orchestrator", "permission_posture.json")))
check("apply: posture 既定 = auto で作成", pj1.get("posture") == "auto")
# --posture 指定（企業向け conservative）と既存尊重
tgt2 = tempfile.mkdtemp(prefix="l1apply2_")
os.makedirs(os.path.join(tgt2, ".claude"))
subprocess.run([sys.executable, APPLY, "--posture", "conservative", tgt2], capture_output=True, text=True)
pj2 = json.load(open(os.path.join(tgt2, ".orchestrator", "permission_posture.json")))
check("apply --posture conservative: 指定どおり作成", pj2.get("posture") == "conservative")
s2 = json.load(open(os.path.join(tgt2, ".claude", "settings.json")))
check("apply --posture conservative: settings.json に defaultMode=default（Manual をリポジトリ単位で強制）",
      s2["permissions"].get("defaultMode") == "default")
subprocess.run([sys.executable, APPLY, tgt2], capture_output=True, text=True)
pj2b = json.load(open(os.path.join(tgt2, ".orchestrator", "permission_posture.json")))
s2b = json.load(open(os.path.join(tgt2, ".claude", "settings.json")))
check("apply 再実行（--posture 無し）: 既存 posture を尊重（auto に上書きしない）", pj2b.get("posture") == "conservative")
check("apply 再実行: defaultMode=default を維持", s2b["permissions"].get("defaultMode") == "default")
subprocess.run([sys.executable, APPLY, "--posture", "auto", tgt2], capture_output=True, text=True)
pj2c = json.load(open(os.path.join(tgt2, ".orchestrator", "permission_posture.json")))
s2c = json.load(open(os.path.join(tgt2, ".claude", "settings.json")))
check("apply --posture auto（再合意）: posture を auto に更新", pj2c.get("posture") == "auto")
check("apply --posture auto: 本スクリプトが書いた defaultMode=default を除去", "defaultMode" not in s2c["permissions"])
pbad = subprocess.run([sys.executable, APPLY, "--posture", "yolo", tgt2], capture_output=True, text=True)
check("apply --posture 不正値: exit1", pbad.returncode == 1)
# プロジェクト settings.json に defaultMode:auto があれば警告（loud）
tgt3 = tempfile.mkdtemp(prefix="l1apply3_")
os.makedirs(os.path.join(tgt3, ".claude"))
json.dump({"permissions": {"defaultMode": "auto"}}, open(os.path.join(tgt3, ".claude", "settings.json"), "w"))
p3 = subprocess.run([sys.executable, APPLY, tgt3], capture_output=True, text=True)
check("apply: プロジェクト settings の defaultMode=auto は無効と警告", "defaultMode" in p3.stdout and "無効" in p3.stdout)
s3 = json.load(open(os.path.join(tgt3, ".claude", "settings.json")))
check("apply: 無効な defaultMode=auto を除去（ユーザー設定の defaultMode を殺さない）", "defaultMode" not in s3["permissions"])
# フレームワーク repo 自身への適用は拒否（自己封鎖・SameFileError の防止）
pself = subprocess.run([sys.executable, APPLY, "--posture", "auto", ROOT], capture_output=True, text=True)
check("apply: フレームワーク自身は SKIP（loud）", pself.returncode == 0 and "SKIP" in pself.stdout and "フレームワーク自身" in pself.stdout)
check("apply: フレームワーク自身の settings.json を触っていない", "Write(.claude/**)" not in open(os.path.join(ROOT, ".claude", "settings.json")).read())

print("\n=== H. autoMode 分類器ルールの導入/除去（~/.claude/settings.json・HOME を差し替えて検証）===")
home = tempfile.mkdtemp(prefix="l1home_")
os.makedirs(os.path.join(home, ".claude"))
user_settings = os.path.join(home, ".claude", "settings.json")
json.dump({"permissions": {"allow": ["Bash(ls *)"]},
           "autoMode": {"soft_deny": ["$defaults", "my own rule"], "allow": ["my own allow (no defaults)"]}},
          open(user_settings, "w"))
henv = dict(os.environ, HOME=home)
ph = subprocess.run([sys.executable, APPLY, "--install-auto-mode-rules"], capture_output=True, text=True, env=henv)
u = json.load(open(user_settings))
tplr = json.load(open(os.path.join(ROOT, "templates", "auto-mode-rules.json")))["autoMode"]
check("install: exit0", ph.returncode == 0)
check("install: hard_deny を $defaults 付きで新設", u["autoMode"].get("hard_deny", [None])[0] == "$defaults"
      and all(r in u["autoMode"]["hard_deny"] for r in tplr["hard_deny"]))
check("install: 既存 soft_deny の独自ルールと $defaults を温存", "my own rule" in u["autoMode"]["soft_deny"] and u["autoMode"]["soft_deny"][0] == "$defaults")
check("install: $defaults の無い allow には足さずに警告", "$defaults" not in u["autoMode"]["allow"] and "⚠" in ph.stdout and "allow" in ph.stdout)
check("install: permissions.allow を温存", u["permissions"]["allow"] == ["Bash(ls *)"])
check("install: バックアップ作成", os.path.exists(user_settings + ".bak"))
before_u = open(user_settings).read()
subprocess.run([sys.executable, APPLY, "--install-auto-mode-rules"], capture_output=True, text=True, env=henv)
check("install: 冪等（2回目で不変）", open(user_settings).read() == before_u)
pr = subprocess.run([sys.executable, APPLY, "--remove-auto-mode-rules"], capture_output=True, text=True, env=henv)
u2 = json.load(open(user_settings))
check("remove: [AI Orchestrator] ルールが全セクションから消える",
      not any(r.startswith("[AI Orchestrator]") for sec in u2.get("autoMode", {}).values() for r in sec))
check("remove: 独自ルールは温存", u2["autoMode"]["soft_deny"] == ["$defaults", "my own rule"] and u2["autoMode"]["allow"] == ["my own allow (no defaults)"])
check("remove: 組み込みのみになった hard_deny セクションは削除", "hard_deny" not in u2.get("autoMode", {}))
# --set-user-default-mode も HOME 差し替えで検証
subprocess.run([sys.executable, APPLY, "--set-user-default-mode", "auto"], capture_output=True, text=True, env=henv)
u3 = json.load(open(user_settings))
check("set-user-default-mode auto: ~/.claude/settings.json に書く", u3["permissions"].get("defaultMode") == "auto")
check("apply: 変更点の報告がある（loud）", "auto_approve" in p1.stdout and "温存" in p1.stdout)
# 冪等性: 2回目実行で settings.json が変わらない
before = open(os.path.join(tgt, ".claude", "settings.json")).read()
subprocess.run([sys.executable, APPLY, tgt], capture_output=True, text=True)
after = open(os.path.join(tgt, ".claude", "settings.json")).read()
check("apply: 冪等（2回目で settings.json 不変）", before == after)

print(f"\n================  RESULT: {passed} passed, {failed} failed  ================")
sys.exit(1 if failed else 0)
