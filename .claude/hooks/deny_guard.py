#!/usr/bin/env python3
"""PreToolUse hook — enforce the HARD-DENY FLOOR.

Blocks irreversible / external / self-privilege operations that a prefix-only
settings.json glob can miss (this regex matches anywhere in the command).
A hook "deny" holds even under --dangerously-skip-permissions.

Fails OPEN on any internal error: if this script can't run, the declarative
permissions.deny rules in settings.json remain as a backstop, and we would
rather not hard-block a whole session because of a hook bug. The floor is
therefore two layers (declarative + this hook), not one.

Standard library only.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from policy import match_deny
except Exception:
    sys.exit(0)  # policy unavailable -> defer to declarative deny rules


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    if data.get("hook_event_name") not in (None, "PreToolUse"):
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    try:
        reason = match_deny(tool_name, tool_input)
    except Exception:
        sys.exit(0)

    if reason:
        out = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"[deny-floor] blocked: {reason}",
            }
        }
        print(json.dumps(out))
        sys.exit(2)  # exit 2 + deny JSON = hard block, even in bypass mode

    sys.exit(0)  # no match -> no decision, normal permission flow continues


if __name__ == "__main__":
    main()
