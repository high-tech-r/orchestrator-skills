#!/usr/bin/env python3
"""Summarize L1 shadow receipts -> Phase 2 allow-list candidates.

Reads <receipts>/*/l1-shadow.jsonl, correlates PreToolUse (intended) with
PostToolUse (executed = approved & ran) by tool_use_id, and prints:
  1. a frequency table of command families, and
  2. a suggested permissions.allow[] block you can review and paste in.

A "promotion candidate" is a command family that is:
  - classified reversible          (verdict == "auto"),
  - seen at least --min times      (default 5), and
  - executed every time intended   (never blocked / rejected).

This is ADVISORY. Read every line before adding it to settings.json — the
classifier is a heuristic, not a proof of safety.

Usage:
  python3 analyze_l1.py [--receipts DIR] [--min N] [--since YYYY-MM-DD]

Standard library only.
"""
import argparse
import glob
import json
import os
from collections import defaultdict


def load(receipts_dir, since):
    pattern = os.path.join(receipts_dir, "*", "l1-shadow.jsonl")
    for path in sorted(glob.glob(pattern)):
        day = os.path.basename(os.path.dirname(path))
        if since and day < since:
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except Exception:
                    continue


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--receipts",
                    default=os.environ.get("L1_RECEIPTS_DIR")
                    or os.path.expanduser("~/.claude/receipts"))
    ap.add_argument("--min", type=int, default=5)
    ap.add_argument("--since", default=None)
    args = ap.parse_args()

    if not os.path.isdir(args.receipts):
        print(f"No receipts directory at {args.receipts}. "
              f"Run some sessions first, or pass --receipts.")
        return

    stats = defaultdict(lambda: {"intended": 0, "verdict": "ask",
                                 "tool": "", "sample": ""})
    intended_by_id = {}
    executed_ids = set()

    for rec in load(args.receipts, args.since):
        ev = rec.get("event")
        key = rec.get("key", "?")
        tid = rec.get("tool_use_id", "")
        if ev == "PreToolUse":
            s = stats[key]
            s["intended"] += 1
            s["verdict"] = rec.get("verdict", "ask")
            s["tool"] = rec.get("tool", "")
            if not s["sample"]:
                s["sample"] = rec.get("raw", "")
            if tid:
                intended_by_id[tid] = key
        elif ev == "PostToolUse":
            if tid:
                executed_ids.add(tid)

    exec_count = defaultdict(int)
    for tid, key in intended_by_id.items():
        if tid in executed_ids:
            exec_count[key] += 1

    rows = [(s["intended"], exec_count.get(key, 0), s["verdict"], key, s["sample"])
            for key, s in stats.items()]
    rows.sort(reverse=True)

    print(f"{'intended':>8} {'exec':>5} {'verdict':>7}  key")
    print("-" * 72)
    for intended, execd, verdict, key, _sample in rows:
        print(f"{intended:>8} {execd:>5} {verdict:>7}  {key}")

    cands = []
    seen = set()
    for intended, execd, verdict, key, _sample in rows:
        if (verdict == "auto" and intended >= args.min
                and execd == intended and key.startswith("Bash:")):
            fam = key.split("Bash: ", 1)[-1]
            rule = f"Bash({fam} *)"
            if rule not in seen:
                seen.add(rule)
                cands.append(rule)

    print()
    if cands:
        print("# Suggested permissions.allow additions (REVIEW before use):")
        print("# reversible Bash families you effectively always let run.")
        print(json.dumps({"permissions": {"allow": sorted(cands)}}, indent=2))
        print("\n# Note: Read/Grep/Glob rarely prompt anyway; add \"Read\",")
        print("# \"Grep\", \"Glob\" (and, if you trust it, \"Edit\") by hand.")
    else:
        print("# No promotion candidates yet — collect a few more days of data,")
        print(f"# or lower --min (currently {args.min}).")


if __name__ == "__main__":
    main()
