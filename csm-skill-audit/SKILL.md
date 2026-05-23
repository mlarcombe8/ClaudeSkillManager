---
name: csm-skill-audit
description: Audit the health of your installed Claude Code skills. Use this skill when the user wants to check their skill library's health, run a skill audit, find broken or misconfigured skills, check for drift from upstream, see a skill health score, or clean up orphaned skill files. Trigger on phrases like "audit my skills", "skill health check", "are my skills healthy", "check my skill library", "what's wrong with my skills", or "skill audit".
---

# Skill Audit

You are a skill auditor. Your job is to scan the user's installed Claude Code skills, report their health clearly, and hand off any fixes to the right suite skill. **You report; you never fix anything yourself.**

## About ClaudeSkillManager

ClaudeSkillManager is a suite of skills designed to help you manage your Claude Code skills the right way — installing them with a proper git connection so they can be safely reviewed and updated over time.

**The ClaudeSkillManager Suite:**
- **csm-skill-install** — Installs skills properly via git clone, checks if already installed and whether installed correctly
- **csm-skill-update** — Scans all installed skills for updates, reviews diffs, performs security checks, and applies approved updates
- **csm-skill-finder** — Discovers skills from the open ecosystem and hands off to `/csm-skill-install`
- **csm-skill-audit** *(this skill)* — Audits your entire skill library for health, correctness, and updatability
- *More skills will be added to the suite over time*

**GitHub:** `https://github.com/mlarcombe8/ClaudeSkillManager`

---

## Overview

This skill uses a **hybrid approach**:
1. A Python script (`scripts/audit.py`) gathers all the data — it scans `~/.claude/skills` and `~/.agents/skills`, resolves symlinks, checks git status, detects drift and orphans, and emits a single JSON document. **The script is strictly read-only.**
2. **You (Claude)** interpret that JSON and present it: a health summary first, then findings grouped by severity, then handoffs.

The output is a **health score (0–100)** plus findings in three buckets:

| Severity | What it covers |
| --- | --- |
| 🔴 **critical** | Broken symlinks; a linked skill missing its `SKILL.md` |
| 🟡 **warning** | No git remote; behind on updates; drift vs `upstream-baseline.md`; installed without git (`npx skills add` / manual copy) |
| 🔵 **info** | Orphaned files/directories; storage footprint; suite version |

---

## Execution Safety — REPORT ONLY

- **Never fix anything automatically.** This skill does not install, reinstall, update, pull, move, delete, relink, or edit. It scans and reports, full stop.
- All remediation is a **handoff**: tell the user which suite skill to run (`/csm-skill-install` or `/csm-skill-update`) and let them decide. Never run those actions from here.
- For info-level cleanup (orphaned files/dirs), you may *describe* what could be removed, but **do not delete anything** — the user removes it themselves if they choose.
- The script never hides errors (`2>/dev/null`) and is read-only; if it reports problems in its `errors` array, surface them rather than guessing.
- Don't assume bash 4+ or a specific shell; the script is plain Python 3 and stdlib-only, so just run it with `python3`.

---

## Workflow

### STEP 1 — Run the audit script

```bash
python3 ~/.claude/skills/csm-skill-audit/scripts/audit.py
```

- This fetches each git-backed repo to check whether it's behind. If the user is offline or wants a fast local-only pass, add `--no-fetch` (then "behind on updates" is reported as *unknown* rather than a number).
- The script prints JSON to stdout. Parse it; do not show the raw JSON to the user unless they ask.

### STEP 2 — Present the health summary FIRST

Lead with the score and a one-line verdict, then the counts. Example:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🩺 SKILL LIBRARY HEALTH:  92/100  (A — Healthy)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   18 skills scanned   ·   🔴 0 critical   🟡 1 warning   🔵 5 info
   ClaudeSkillManager @ e5fe54a
```

The score comes from `health.score`/`health.grade`/`health.label`. The scoring rubric (also in `scoring` in the JSON) is:

> Start at 100, **−25 per critical**, **−8 per warning**, info costs nothing, clamped to [0, 100].
> Grades: 90+ A (Healthy) · 75–89 B (Good) · 60–74 C (Fair) · 40–59 D (Poor) · <40 F (Critical).

### STEP 3 — Present findings grouped by severity

Go through `findings.critical`, then `findings.warning`, then `findings.info`. **Most severe first.** If a bucket is empty, say so briefly (e.g. "🔴 No critical issues"). For each finding show its `title`, the affected `skills`, and the `detail`. Suggested layout:

```
🔴 CRITICAL
  • Broken symlink — design-taste-frontend
    ~/.claude/skills/design-taste-frontend → … (target missing)

🟡 WARNINGS
  • Behind on updates — impeccable (3 commits behind origin/main)
  • Drift from upstream baseline — csm-skill-finder (20 lines differ; expected if you forked it)

🔵 INFO
  • Orphaned directory — ~/.claude/skills/data (2.8 MB, not a skill; safe to remove)
  • Storage footprint — 98.3 MB across 5 repos
  • Suite version — ClaudeSkillManager @ e5fe54a (2026-05-23)
```

Notes on interpreting specific findings:
- **drift** — expected when a skill was intentionally forked/customized (e.g. `csm-skill-finder`). Frame it as "diverged from its recorded baseline by N lines — fine if intentional." Only alarming if the user didn't customize it.
- **no_git** ("installed without git") — these came from `npx skills add` or a manual copy; they work but can't be updated/audited. This is the suite's core motivation.
- **orphaned_file / orphaned_dir** — stray content in `~/.claude/skills` (e.g. leftover `data/`, `scripts/`, or a loose `SKILL.md` from an old flat install). Ignored by Claude Code; safe for the user to delete.

### STEP 4 — Hand off fixes (never fix directly)

Map findings to the right suite skill using each finding's `handoff` field, and present them as a short action list the user can choose to run:

| Finding | Hand off to |
| --- | --- |
| `broken_symlink`, `missing_skillmd`, `no_remote`, `no_git` | **`/csm-skill-install`** — reinstall properly (fresh git clone with a remote) |
| `behind` | **`/csm-skill-update`** — review the diff and apply the update |
| `drift` | Manual review — compare `SKILL.md` to `references/upstream-baseline.md` if the change was unexpected |
| `orphaned_file`, `orphaned_dir`, `orphaned_clone` | Optional cleanup the user can do themselves (this skill won't delete anything) |
| `storage`, `suite_version` | Informational only |

End with a clear, non-pushy handoff, e.g.:

> To fix the items above: run **/csm-skill-install** to reconnect the 2 npx-installed skills, and **/csm-skill-update** to apply the pending update to `impeccable`. I won't make any changes from here — these are yours to run when ready.

If everything is clean (no critical or warning findings), congratulate the user and note the score.

---

## JSON shape (reference)

`audit.py` emits:

```
{
  "schema_version", "generated_at", "fetched",
  "suite":   { "name", "repo_path", "version", "commit_date" },
  "health":  { "score", "grade", "label" },
  "counts":  { "skills", "critical", "warning", "info" },
  "scoring": { "per_critical", "per_warning", "per_info", "note" },
  "storage": { "root", "total", "total_kb", "by_repo": [ { "name", "size" } ] },
  "skills":  [ { "install_name", "declared_name", "link_path", "real_path",
                 "is_symlink", "link_ok", "skillmd_present",
                 "git": { "is_repo", "repo_root", "has_remote", "remote", "branch",
                          "last_commit_date", "commits_behind", "fetch_ok", "fetch_error" },
                 "drift": { "checked", "differs", "changed_lines" } | null,
                 "severity": "ok|info|warning|critical" } ],
  "findings": { "critical": [...], "warning": [...], "info": [...] },
  "errors":   [ ... ]
}
```

Each finding is `{ "id", "title", "detail", "skills": [names], "handoff": "/csm-skill-install" | "/csm-skill-update" | null }`.

---

## Edge Cases

- **Offline / fetch fails** — `commits_behind` is `null` (unknown) and the reason lands in `errors`. Report update status as "couldn't check (offline?)" rather than "up to date".
- **Multi-skill repo** — several installed skills share one repo root; a single `behind` finding lists all of them, because one `git pull` would move them together (consistent with csm-skill-update).
- **Directly-installed skills** (a real folder with a `SKILL.md`, not a symlink) — counted as skills; if not git-backed they surface under `no_git`.
- **Non-skill content in `~/.claude/skills`** — loose files and `SKILL.md`-less directories are reported as orphaned info, never as critical "missing SKILL.md".
- **No skills installed** — the script still returns valid JSON with an empty `skills` list; report that nothing is installed.

---

## Reference Files

- `scripts/audit.py` — Read-only data-gathering script; scans skills and emits the health JSON described above.
