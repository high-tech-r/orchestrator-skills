#!/usr/bin/env python3
"""PreToolUse hook — posture-driven permission gate (auto-mode aware).

Reads the project's chosen **permission posture** and decides whether to skip
the normal approval prompt. The hard-deny floor is enforced FIRST and holds in
every posture and every Claude Code permission mode (a hook "deny" blocks even
in auto / bypassPermissions).

Postures (CLAUDE.md Rule 9 / docs/security/PERMISSION_POSTURE.md):
  - auto (recommended default): Claude Code's native **auto mode** is the
    authority. Its background classifier approves/blocks each action; this hook
    adds NOTHING on the allow side — it only enforces the deny floor and logs.
    If the session is NOT actually in auto mode (hook input `permission_mode`
    != "auto": ineligible account, admin disabled it, or launched in another
    mode), the hook behaves as conservative and says so once per session
    (loud; never silently pretend auto-approval is happening).
  - conservative: never auto-approve from the hook. Floor + observe only.
  - balanced: hook auto-approves ops the reversibility classifier calls "auto"
    (reversible / local / read-only). Everything else prompts.
  - permissive: hook auto-approves everything not on the deny floor and records
    what a human would have been asked (would_have_asked).

  balanced / permissive exist for sessions WITHOUT auto mode (older versions,
  disableAutoMode, headless -p). When such a session IS in auto mode, the hook
  defers to the native classifier instead of emitting "allow" (the classifier
  is the stricter, better-informed gate) and notes that once per session.

Posture resolution (cheap, fail-safe, LOUD on degradation):
  ORCH_POSTURE env  >  .orchestrator/permission_posture.json[.posture]  >  SAFE_POSTURE
If the config exists but is unreadable/invalid/unknown, fall back to the SAFEST
hook behaviour (conservative = no hook-side allow) and print a stderr warning
plus a systemMessage. File absent (first run) = conservative, silently.

Contract notes:
  * A hook "allow" cannot override a settings.json `deny` or `ask` rule, so the
    ops in permissions.ask (git push / reset --hard / rebase) still prompt in
    every posture and in auto mode — the recommended way to carve exceptions.
  * stdout must contain at most one JSON object for this hook's process. This is
    the only PreToolUse hook that emits a decision; deny_guard emits only on a
    floor hit, l1_shadow_log stays silent.
  * `permissions.defaultMode: "auto"` does NOT take effect from a project
    .claude/settings.json — only from ~/.claude/settings.json / managed settings
    / --permission-mode auto. The hook therefore cannot "turn on" auto mode; it
    can only observe which mode the session is in and be honest about it.
  * Never breaks a session: every branch defaults to the safe side; logging
    failures are swallowed.

Standard library only.
Receipts: $L1_RECEIPTS_DIR/<YYYY-MM-DD>/l1-decisions.jsonl  (default ~/.claude/receipts)
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from policy import classify, match_deny, normalize_key, redact
except Exception:
    sys.exit(0)  # policy unavailable -> defer to declarative rules + deny_guard

VALID_POSTURES = ("auto", "conservative", "balanced", "permissive")
SAFE_POSTURE = "conservative"
RECOMMENDED_POSTURE = "auto"


def project_dir():
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return env
    # .../<root>/.claude/hooks/permission_gate.py -> three levels up is <root>
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def receipts_dir():
    base = os.environ.get("L1_RECEIPTS_DIR") or os.path.expanduser("~/.claude/receipts")
    d = os.path.join(base, datetime.date.today().isoformat())
    os.makedirs(d, exist_ok=True)
    return d


def resolve_posture():
    """ORCH_POSTURE env > posture config file > conservative. Fail-safe + loud.
    Returns (posture, warning_or_None)."""
    env = os.environ.get("ORCH_POSTURE")
    if env:
        if env in VALID_POSTURES:
            return env, None
        return SAFE_POSTURE, (f"権限ポスチャ: ORCH_POSTURE='{env}' は不正値です。"
                              f"{SAFE_POSTURE} にフォールバックしました。")
    path = os.path.join(project_dir(), ".orchestrator", "permission_posture.json")
    if not os.path.exists(path):
        return SAFE_POSTURE, None  # documented default, not a degradation
    try:
        with open(path, encoding="utf-8") as f:
            posture = (json.load(f) or {}).get("posture")
    except Exception as e:
        return SAFE_POSTURE, (f"権限ポスチャ: {path} を読めず（{e.__class__.__name__}）"
                              f"{SAFE_POSTURE} にフォールバックしました。")
    if posture in VALID_POSTURES:
        return posture, None
    return SAFE_POSTURE, (f"権限ポスチャ: {path} の posture='{posture}' は不正値です。"
                          f"{SAFE_POSTURE} にフォールバックしました。")


def once_per_session(session_id, key):
    """True the first time (session, key) is seen today; marker lives in the
    receipts dir so a noisy notice is shown once, not on every tool call."""
    if not session_id:
        return True
    try:
        marker = os.path.join(receipts_dir(), f".notice-{key}-{session_id}")
        if os.path.exists(marker):
            return False
        with open(marker, "w", encoding="utf-8") as f:
            f.write(datetime.datetime.now().isoformat(timespec="seconds"))
        return True
    except Exception:
        return True


def log(rec):
    try:
        with open(os.path.join(receipts_dir(), "l1-decisions.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        # best-effort telemetry: a receipt-write failure must never break a
        # session, and this hook exits 0 so stderr would not surface anyway.
        pass


def emit(decision=None, reason=None, system_message=None):
    """Print the single JSON object this hook is allowed to emit (or nothing)."""
    out = {}
    if decision:
        out["hookSpecificOutput"] = {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    if system_message:
        out["systemMessage"] = system_message
    if out:
        print(json.dumps(out, ensure_ascii=False))


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool = data.get("tool_name", "")
    ti = data.get("tool_input", {}) or {}
    session = data.get("session_id", "")
    mode = data.get("permission_mode")  # "auto" / "default" / ... ; None on old versions
    posture, warn = resolve_posture()
    if warn:
        print("⚠ " + warn, file=sys.stderr)

    rec = {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "session": session,
        "tool_use_id": data.get("tool_use_id", ""),
        "tool": tool,
        "key": normalize_key(tool, ti),
        "raw": redact(ti.get("command") or ti.get("file_path") or "")[:400],
        "posture": posture,
        "permission_mode": mode,
    }

    # 1. deny floor — enforced first, holds in EVERY posture and EVERY mode.
    try:
        deny_reason = match_deny(tool, ti)
    except Exception:
        deny_reason = None
    if deny_reason:
        rec.update(verdict="deny", decision="deny", reason=deny_reason)
        log(rec)
        emit("deny", f"[deny-floor] blocked: {deny_reason}")
        sys.exit(2)

    try:
        verdict = classify(tool, ti)
    except Exception:
        verdict = "ask"
    rec["verdict"] = verdict

    notice = ("⚠ " + warn) if (warn and once_per_session(session, "posture-fallback")) else None

    # 2. Session is in Claude Code auto mode: the native classifier is the
    #    authority. Never emit "allow" here (floor + observe only).
    if mode == "auto":
        if posture in ("balanced", "permissive") and once_per_session(session, "defer-classifier"):
            notice = (f"権限ポスチャ '{posture}' ですが、このセッションは Claude Code の auto mode です。"
                      f"フック側の自動承認は行わず、auto mode の分類器に委ねます（deny フロアは常時有効）。"
                      f"ポスチャを 'auto' に揃えることを推奨します。")
        elif posture == "conservative" and once_per_session(session, "conservative-in-auto"):
            notice = ("権限ポスチャは 'conservative'（Manual 想定）ですが、このセッションは auto mode で動いています"
                      "（`--permission-mode auto` か managed settings がプロジェクト設定を上書き）。分類器が自動承認します。"
                      "全操作を人が承認したい場合は auto mode を切って起動してください"
                      "（`python3 scripts/apply_posture.py --posture conservative .` でプロジェクトに Manual を書けます）。")
        rec.update(decision="classifier", reason="auto mode: native classifier decides")
        log(rec)
        emit(system_message=notice)
        sys.exit(0)

    # 3. posture=auto but the session is NOT in auto mode -> behave as
    #    conservative, and say so once (never pretend auto-approval exists).
    if posture == "auto":
        if mode is not None and once_per_session(session, "auto-not-active"):
            notice = (f"権限ポスチャは 'auto' ですが、このセッションの permission_mode は '{mode}' です"
                      f"（auto mode が利用不可／別モードで起動）。フックは自動承認しません（conservative 相当）。"
                      f"auto mode で動かすには `claude --permission-mode auto`、または ~/.claude/settings.json の "
                      f"permissions.defaultMode を \"auto\" にしてください（プロジェクトの .claude/settings.json では無効）。")
        rec.update(decision="prompt", reason=f"auto posture without auto mode (mode={mode}): human approves")
        log(rec)
        emit(system_message=notice)
        sys.exit(0)

    # 4. conservative: never auto-approve. Observe + floor only; human approves.
    if posture == "conservative":
        rec.update(decision="prompt", reason="conservative: human approves")
        log(rec)
        emit(system_message=notice)
        sys.exit(0)

    # 5. balanced & permissive (no auto mode): reversible/local/read-only -> skip the prompt.
    if verdict == "auto":
        rec.update(decision="allow", reason="reversible")
        log(rec)
        emit("allow", "[auto] reversible operation", notice)
        sys.exit(0)

    # 6. permissive: approve the rest too (still not on the floor), but record
    #    that a human would have been asked.
    if posture == "permissive":
        rec.update(decision="allow", reason="permissive override (would_have_asked)")
        log(rec)
        emit("allow", "[permissive] auto-approved; review the receipt", notice)
        sys.exit(0)

    # 7. balanced default: no decision, the normal permission prompt appears.
    rec.update(decision="prompt", reason="would_have_asked")
    log(rec)
    emit(system_message=notice)
    sys.exit(0)


if __name__ == "__main__":
    main()
