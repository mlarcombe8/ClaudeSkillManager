#!/usr/bin/env python3
"""
csm_log.py — shared activity logger for the ClaudeSkillManager suite.

Appends one JSON object per line (JSON Lines) to ~/.csm/csm.log so the suite
keeps a human-readable, parseable record of what it has done. Used by every
skill (csm-skill-install / -update / -audit) at the moment an action completes.

It is **best-effort**: it never raises into the calling workflow. If the log
can't be written, it prints a notice to stderr and still exits 0, so a logging
hiccup can never break an install, update, or audit.

Each entry has, in this order:
  timestamp  ISO-8601 with timezone (e.g. 2026-05-24T10:30:00-04:00)
  skill      the skill's install name, or "all" for suite-wide actions
  action     installed | reinstalled | skipped | failed | checked |
             updated | skipped-update | audit-run | scan-run
  source     GitHub URL where applicable (else "")
  result     success | failure | up-to-date
  details    brief plain-English summary

Usage:
  python3 csm_log.py --skill <name|all> --action <action> \
      --result <success|failure|up-to-date> [--source <url>] --details "<text>"
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

LOG_DIR = Path.home() / ".csm"
LOG_FILE = LOG_DIR / "csm.log"

# Accepted values (not strictly enforced — logging stays forgiving — but
# documented here and surfaced via --help so callers stay consistent).
ACTIONS = ("installed", "reinstalled", "skipped", "failed", "checked",
           "updated", "skipped-update", "audit-run", "scan-run")
RESULTS = ("success", "failure", "up-to-date")


def main():
    parser = argparse.ArgumentParser(
        description="Append one JSON-lines entry to ~/.csm/csm.log (best-effort).")
    parser.add_argument("--skill", required=True,
                        help='Skill install name, or "all" for suite-wide actions.')
    parser.add_argument("--action", required=True,
                        help="One of: " + ", ".join(ACTIONS))
    parser.add_argument("--result", required=True,
                        help="One of: " + ", ".join(RESULTS))
    parser.add_argument("--source", default="",
                        help="GitHub URL where applicable.")
    parser.add_argument("--details", default="",
                        help="Brief plain-English summary of what happened.")
    args = parser.parse_args()

    entry = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "skill": args.skill,
        "action": args.action,
        "source": args.source,
        "result": args.result,
        "details": args.details,
    }

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print("logged: %s / %s / %s -> %s" % (args.skill, args.action, args.result, LOG_FILE))
    except OSError as exc:
        print("csm_log: could not write %s (%s) — continuing without logging"
              % (LOG_FILE, exc), file=sys.stderr)

    # Always succeed: logging must never break the calling workflow.
    sys.exit(0)


if __name__ == "__main__":
    main()
