#!/usr/bin/env python3
"""権限ポスチャ一式の検証ハーネス（保守者向け・ライブ Claude Code セッション不要）。

合成した PreToolUse JSON を stdin からフックに流し、決定表どおりに動くかを検証する:
  A. permission_gate の決定表（conservative/balanced/permissive × floor/可逆/その他）
  A2. 壊れた config → conservative フォールバック＋loud（stderr 警告）
  B. ポスチャ切替スモーク（config ファイル経由）＋ deny フロア常時ON
  B2. deny_guard 単独（floor → exit2 / それ以外 → exit0）
  C. analyze_l1 E2E（レシート → allow-list 候補）
  D. redact（レシートに秘密が平文で残らない）
  E. settings.json 健全性（配線順・ask/deny）
  F. 自己権限フロアの限定（settings/hooks はブロック・skills/agents は許可）
  G. apply_posture.py（既存PJ導入スクリプト: 独自フック/allow 温存・冪等）

実行: python3 scripts/verify_permission_hooks.py   （終了コード 0=全PASS / 1=失敗あり）
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(ROOT, ".claude", "hooks")
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
    if not stdout:
        return None
    try:
        return json.loads(stdout)["hookSpecificOutput"]["permissionDecision"]
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

print("\n=== A2. 壊れた config -> conservative フォールバック + loud ===")
bad_dir = tempfile.mkdtemp(prefix="l1bad_")
os.makedirs(os.path.join(bad_dir, ".orchestrator"))
with open(os.path.join(bad_dir, ".orchestrator", "permission_posture.json"), "w") as f:
    f.write("{garbage not json")
env = {k: v for k, v in os.environ.items() if k != "ORCH_POSTURE"}
env["CLAUDE_PROJECT_DIR"] = bad_dir
env["L1_RECEIPTS_DIR"] = tmp_rcpt
rc, out, err = run(GATE, bash("ls -la"), env=env)
check(f"壊れconfig: ls -> prompt(no stdout) (dec={decision_of(out)})", decision_of(out) is None and rc == 0)
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
expect_ls = {"conservative": None, "balanced": "allow", "permissive": "allow"}
for posture in ("conservative", "balanced", "permissive"):
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
check("apply: posture = conservative で作成", pj1.get("posture") == "conservative")
check("apply: 変更点の報告がある（loud）", "auto_approve" in p1.stdout and "温存" in p1.stdout)
# 冪等性: 2回目実行で settings.json が変わらない
before = open(os.path.join(tgt, ".claude", "settings.json")).read()
subprocess.run([sys.executable, APPLY, tgt], capture_output=True, text=True)
after = open(os.path.join(tgt, ".claude", "settings.json")).read()
check("apply: 冪等（2回目で settings.json 不変）", before == after)

print(f"\n================  RESULT: {passed} passed, {failed} failed  ================")
sys.exit(1 if failed else 0)
