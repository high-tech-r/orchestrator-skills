#!/usr/bin/env python3
"""PreToolUse + PostToolUse hook — OBSERVE ONLY (Phase 0 / L1 shadow mode).

Logs every tool call the agent attempts, plus an advisory reversibility
verdict, to a daily JSONL receipt. It emits NO permission decision, so you
still see the normal approval prompt and still press yes yourself. The point
of Phase 0 is to gather real data on "what do I actually always approve?"
without changing any behaviour yet.

  - PreToolUse  record => the agent *intended* an operation (+ verdict)
  - PostToolUse record => that operation actually *ran* (i.e. was approved)
Correlate the two by tool_use_id later (see scripts/analyze_l1.py).

Never blocks, never crashes the session: always exits 0.
Standard library only.

Receipts dir: $L1_RECEIPTS_DIR  (default: ~/.claude/receipts)
Layout:       <receipts>/<YYYY-MM-DD>/l1-shadow.jsonl
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from policy import classify, normalize_key, redact
except Exception:
    sys.exit(0)


def receipts_file():
    base = os.environ.get("L1_RECEIPTS_DIR") or os.path.expanduser("~/.claude/receipts")
    day = datetime.date.today().isoformat()
    d = os.path.join(base, day)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "l1-shadow.jsonl")


def truncate(s, n=400):
    s = s or ""
    return s if len(s) <= n else s[:n] + "\u2026"


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    event = data.get("hook_event_name", "")
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {}) or {}

    rec = {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "event": event,
        "session": data.get("session_id", ""),
        "tool_use_id": data.get("tool_use_id", ""),
        "tool": tool_name,
        "key": normalize_key(tool_name, tool_input),
        "cwd": data.get("cwd", ""),
    }
    # redact() masks secrets in the sample BEFORE it is written to disk; the
    # command family key (rec["key"]) is computed separately and is unaffected.
    if tool_name == "Bash":
        rec["raw"] = truncate(redact(tool_input.get("command", "")))
    elif "file_path" in tool_input:
        rec["raw"] = truncate(redact(tool_input.get("file_path", "")))

    if event == "PreToolUse":
        try:
            rec["verdict"] = classify(tool_name, tool_input)
        except Exception:
            rec["verdict"] = "ask"

    try:
        with open(receipts_file(), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass

    sys.exit(0)  # observe only: never emit a permission decision


if __name__ == "__main__":
    main()
