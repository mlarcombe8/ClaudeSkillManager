# ClaudeSkillManager

A suite of [Claude Code](https://claude.com/claude-code) skills for installing, updating, and auditing skills **properly** — that is, with a real git connection back to each skill's source so it can be reviewed, updated, and rolled back over time.

## Quick install

```sh
curl -fsSL https://raw.githubusercontent.com/mlarcombe8/ClaudeSkillManager/main/install.sh | sh
```

This clones the suite and symlinks its four skills into `~/.claude/skills`. **Why a clone instead of a copy?** Installing as a `git clone` keeps a live remote back to GitHub, so the skills stay **updatable**, **rollback-able**, and **auditable** over time — none of which is possible with a plain file copy or `npx skills add`.

The installer is POSIX `sh`, idempotent (it skips any skill that's already linked), and verifies every link before reporting success. When it finishes, **start a new Claude Code session** so the skills load.

## Manual install

Prefer not to pipe a script to your shell? Do the same steps by hand:

```sh
# 1. Clone the suite (keeps a git remote, so it stays updatable/auditable)
git clone https://github.com/mlarcombe8/ClaudeSkillManager.git ~/.agents/skills/ClaudeSkillManager

# 2. Make sure your skills directory exists
mkdir -p ~/.claude/skills

# 3. Symlink each skill into ~/.claude/skills
ln -s ~/.agents/skills/ClaudeSkillManager/csm-skill-install ~/.claude/skills/csm-skill-install
ln -s ~/.agents/skills/ClaudeSkillManager/csm-skill-update  ~/.claude/skills/csm-skill-update
ln -s ~/.agents/skills/ClaudeSkillManager/csm-skill-finder  ~/.claude/skills/csm-skill-finder
ln -s ~/.agents/skills/ClaudeSkillManager/csm-skill-audit   ~/.claude/skills/csm-skill-audit

# 4. Verify the links resolve
ls -l ~/.claude/skills | grep csm-skill
```

Each subfolder is a self-contained skill (its own `SKILL.md`); Claude Code discovers skills under `~/.claude/skills`. Start a new Claude Code session for them to load, then try `/csm-skill-audit`.

## Why "properly"?

When a skill is installed by a plain file copy or download, it lives on your machine but has no link to its origin on GitHub. That means you can't check for updates, can't see what changed between versions, and can't roll back if an update breaks something. The skills in this suite install each skill as a git clone with a remote, so all of that becomes possible.

## Skills in this suite

| Skill | What it does |
| --- | --- |
| [`csm-skill-install`](csm-skill-install/) | Installs Claude Code skills via `git clone` with a remote. Triggers on "install skill", "add skill", "get skill", "set up X". |
| [`csm-skill-update`](csm-skill-update/) | Scans installed skills, groups them by the git repo that backs them, fetches and diffs available updates, summarizes changes in plain English, flags security concerns, and applies only the updates you approve. |
| [`csm-skill-finder`](csm-skill-finder/) | Discovers skills from the open ecosystem (`npx skills find`, the skills.sh leaderboard), vets candidates by install count/source/stars, and hands off installs to `/csm-skill-install`. |
| [`csm-skill-audit`](csm-skill-audit/) | Audits your whole skill library and reports a health score with findings grouped by severity (broken symlinks, no git remote, behind on updates, drift, orphaned files). Read-only — it hands off fixes to `csm-skill-install`/`csm-skill-update`. |

## Repository layout

```
ClaudeSkillManager/
├── install.sh                # one-shot POSIX installer (clone + symlinks)
├── csm-skill-install/
│   ├── SKILL.md
│   └── references/
├── csm-skill-update/
│   ├── SKILL.md
│   ├── references/
│   └── scripts/
├── csm-skill-finder/
│   ├── SKILL.md
│   └── references/        # incl. upstream-baseline.md for drift detection
└── csm-skill-audit/
    ├── SKILL.md
    └── scripts/           # audit.py (read-only health scan → JSON)
```
