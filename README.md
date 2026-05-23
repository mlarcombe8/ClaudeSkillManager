# ClaudeSkillManager

A suite of [Claude Code](https://claude.com/claude-code) skills for installing, updating, and auditing skills **properly** — that is, with a real git connection back to each skill's source so it can be reviewed, updated, and rolled back over time.

## Why "properly"?

When a skill is installed by a plain file copy or download, it lives on your machine but has no link to its origin on GitHub. That means you can't check for updates, can't see what changed between versions, and can't roll back if an update breaks something. The skills in this suite install each skill as a git clone with a remote, so all of that becomes possible.

## Skills in this suite

| Skill | What it does |
| --- | --- |
| [`skill-install`](skill-install/) | Installs Claude Code skills via `git clone` with a remote. Triggers on "install skill", "add skill", "get skill", "set up X". |
| [`skill-update-manager`](skill-update-manager/) | Scans installed skills, groups them by the git repo that backs them, fetches and diffs available updates, summarizes changes in plain English, flags security concerns, and applies only the updates you approve. |
| [`skill-finder`](skill-finder/) | Discovers skills from the open ecosystem (`npx skills find`, the skills.sh leaderboard), vets candidates by install count/source/stars, and hands off installs to `/skill-install`. |
| [`skill-audit`](skill-audit/) | Audits your whole skill library and reports a health score with findings grouped by severity (broken symlinks, no git remote, behind on updates, drift, orphaned files). Read-only — it hands off fixes to `skill-install`/`skill-update-manager`. |

## Installation

Clone this repository into your skills directory:

```bash
git clone https://github.com/mlarcombe8/ClaudeSkillManager.git ~/.agents/skills/ClaudeSkillManager
```

Each subfolder is a self-contained skill (each has its own `SKILL.md`). Claude Code discovers skills under `~/.claude/skills` and `~/.agents/skills`, so once cloned the skills are available.

## Repository layout

```
ClaudeSkillManager/
├── skill-install/
│   ├── SKILL.md
│   └── references/
├── skill-update-manager/
│   ├── SKILL.md
│   ├── references/
│   └── scripts/
├── skill-finder/
│   ├── SKILL.md
│   └── references/        # incl. upstream-baseline.md for drift detection
└── skill-audit/
    ├── SKILL.md
    └── scripts/           # audit.py (read-only health scan → JSON)
```
