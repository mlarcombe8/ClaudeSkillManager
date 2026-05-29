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

Extra structured fields can be attached with repeatable `--field NAME=VALUE`
(e.g. `--field skills_scanned=19`), stored as JSON numbers/booleans where
possible so readers never have to parse them out of `details`.

Usage:
  python3 csm_log.py --skill <name|all> --action <action> \
      --result <success|failure|up-to-date> [--source <url>] \
      [--field NAME=VALUE ...] --details "<text>"
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
           "updated", "skipped-update", "rolled-back", "uninstalled",
           "audit-run", "scan-run")
RESULTS = ("success", "failure", "up-to-date")

# Standard fields are managed explicitly; extra --field entries may not clobber
# them (use the dedicated flags for those).
RESERVED = ("timestamp", "skill", "action", "source", "result", "details")


def _coerce(value):
    """Turn a string value into int/float/bool when it clearly is one.

    Lets callers pass structured data like `--field skills_scanned=19` and have
    it stored as the JSON number 19 (not the string "19"), so readers never have
    to parse it back out of free text.
    """
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    low = value.strip().lower()
    if low in ("true", "false"):
        return low == "true"
    return value


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
    parser.add_argument("--field", action="append", default=[], metavar="NAME=VALUE",
                        help="Extra structured field to include in the entry, e.g. "
                             "--field skills_scanned=19. Repeatable. Numeric/boolean "
                             "values are stored as JSON numbers/booleans. Reserved "
                             "names (%s) are ignored." % ", ".join(RESERVED))
    args = parser.parse_args()

    # Standard fields first (details kept last so any extra structured fields
    # sit between `result` and the human-readable `details`).
    entry = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "skill": args.skill,
        "action": args.action,
        "source": args.source,
        "result": args.result,
    }
    for raw in args.field:
        if "=" not in raw:
            continue  # ignore malformed --field with no '='
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key or key in RESERVED:
            continue  # never let an extra field clobber a standard one
        entry[key] = _coerce(value)
    entry["details"] = args.details

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
