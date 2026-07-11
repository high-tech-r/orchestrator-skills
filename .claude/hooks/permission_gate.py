#!/usr/bin/env python3
"""PreToolUse hook — posture-driven auto-approval gate.

This is the posture-aware successor to the old `auto_approve.py`. It reads the
project's chosen **permission posture** and decides whether to skip the normal
approval prompt for an operation. The hard-deny floor is enforced FIRST and
holds in every posture.

Posture (see CLAUDE.md Rule 9 / docs/security/PERMISSION_POSTURE.md):
  - conservative (default): never auto-approve. Enforce the deny floor, observe,
    and let the human approve everything. A company dropping the framework in
    gets STRICTLY MORE protection than vanilla Claude Code and ZERO surprise
    auto-approvals.
  - balanced: auto-approve operations the reversibility classifier calls "auto"
    (reversible / local / read-only). Everything else still prompts.
  - permissive: auto-approve everything not on the deny floor; record the ones a
    human would have been asked about (would_have_asked) for post-hoc review.

Posture resolution (cheap, fail-safe, LOUD on degradation):
  ORCH_POSTURE env  >  .orchestrator/permission_posture.json[.posture]  >  "conservative"
If the config exists but is unreadable/invalid/unknown, fall back to the SAFEST
posture (conservative) and print a one-line stderr warning — never silently
degrade (matches honesty_check.py's contract). File absent (first run) =
conservative, silently (that is the documented default, not a degradation).

Contract notes:
  * A hook "allow" cannot override a settings.json `deny` or `ask` rule, so the
    ops in permissions.ask (git push / reset --hard / rebase) still prompt even
    under permissive — the recommended way to carve exceptions without touching
    the floor.
  * stdout must contain exactly one JSON object *for this hook's process*. This
    is the only PreToolUse hook that emits a decision; deny_guard emits only on
    a floor hit, l1_shadow_log stays silent.
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

VALID_POSTURES = ("conservative", "balanced", "permissive")
SAFE_POSTURE = "conservative"


def project_dir():
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return env
    # .../<root>/.claude/hooks/permission_gate.py -> three levels up is <root>
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def resolve_posture():
    """ORCH_POSTURE env > posture config file > conservative. Fail-safe + loud."""
    env = os.environ.get("ORCH_POSTURE")
    if env:
        if env in VALID_POSTURES:
            return env
        print(f"⚠ 権限ポスチャ: ORCH_POSTURE='{env}' は不正値です。"
              f"{SAFE_POSTURE} にフォールバックしました。", file=sys.stderr)
        return SAFE_POSTURE
    path = os.path.join(project_dir(), ".orchestrator", "permission_posture.json")
    if not os.path.exists(path):
        return SAFE_POSTURE  # documented default, not a degradation
    try:
        with open(path, encoding="utf-8") as f:
            posture = (json.load(f) or {}).get("posture")
    except Exception as e:
        print(f"⚠ 権限ポスチャ: {path} を読めず（{e.__class__.__name__}）"
              f"{SAFE_POSTURE} にフォールバックしました。", file=sys.stderr)
        return SAFE_POSTURE
    if posture in VALID_POSTURES:
        return posture
    print(f"⚠ 権限ポスチャ: {path} の posture='{posture}' は不正値です。"
          f"{SAFE_POSTURE} にフォールバックしました。", file=sys.stderr)
    return SAFE_POSTURE


def log(rec):
    base = os.environ.get("L1_RECEIPTS_DIR") or os.path.expanduser("~/.claude/receipts")
    try:
        d = os.path.join(base, datetime.date.today().isoformat())
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "l1-decisions.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        # best-effort telemetry: a receipt-write failure must never break a
        # session, and this hook exits 0 so stderr would not surface anyway.
        pass


def emit(decision, reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }))


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool = data.get("tool_name", "")
    ti = data.get("tool_input", {}) or {}
    posture = resolve_posture()

    rec = {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "session": data.get("session_id", ""),
        "tool_use_id": data.get("tool_use_id", ""),
        "tool": tool,
        "key": normalize_key(tool, ti),
        "raw": redact(ti.get("command") or ti.get("file_path") or "")[:400],
        "posture": posture,
    }

    # 1. deny floor — enforced first, holds in EVERY posture (even permissive).
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

    # 2. conservative: never auto-approve. Observe + floor only; human approves.
    if posture == "conservative":
        rec.update(decision="prompt", reason="conservative: human approves")
        log(rec)
        sys.exit(0)

    # 3. balanced & permissive: reversible/local/read-only -> skip the prompt.
    if verdict == "auto":
        rec.update(decision="allow", reason="reversible")
        log(rec)
        emit("allow", "[auto] reversible operation")
        sys.exit(0)

    # 4. permissive: approve the rest too (still not on the floor), but record
    #    that a human would have been asked.
    if posture == "permissive":
        rec.update(decision="allow", reason="permissive override (would_have_asked)")
        log(rec)
        emit("allow", "[permissive] auto-approved; review the receipt")
        sys.exit(0)

    # 5. balanced default: no decision, the normal permission prompt appears.
    rec.update(decision="prompt", reason="would_have_asked")
    log(rec)
    sys.exit(0)


if __name__ == "__main__":
    main()
