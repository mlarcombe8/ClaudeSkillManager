# ClaudeSkillManager

A suite of [Claude Code](https://claude.com/claude-code) skills for installing, updating, and auditing skills **properly** — that is, with a real git connection back to each skill's source so it can be reviewed, updated, and rolled back over time.

## Why git-connected installs matter

When a skill is installed by a plain file copy or download, it lives on your machine but has no link to its origin on GitHub. That means you can't check for updates, can't see what changed between versions, and can't roll back if an update breaks something. The skills in this suite install each skill as a git clone with a remote, so all of that becomes possible.

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

## Skills in this suite

| Skill | What it does |
| --- | --- |
| [`csm-skill-install`](csm-skill-install/) | Installs Claude Code skills via `git clone` with a remote. Triggers on "install skill", "add skill", "get skill", "set up X". |
| [`csm-skill-update`](csm-skill-update/) | Scans installed skills, groups them by the git repo that backs them, fetches and diffs available updates, summarizes changes in plain English, flags security concerns, and applies only the updates you approve. |
| [`csm-skill-finder`](csm-skill-finder/) | Discovers skills from the open ecosystem (`npx skills find`, the skills.sh leaderboard), vets candidates by install count/source/stars, and hands off installs to `/csm-skill-install`. |
| [`csm-skill-audit`](csm-skill-audit/) | Audits your whole skill library and reports a health score with findings grouped by severity (broken symlinks, no git remote, behind on updates, drift, orphaned files). Also offers a **deep security scan** (`--scan`) that analyzes each skill's contents for risky behavior. Read-only — it hands off fixes to `csm-skill-install`/`csm-skill-update`. |

## Security

Three of the skills review skill code for risky behavior, at different moments:

- **`csm-skill-install`** runs a **static analysis** of a skill's `SKILL.md` and any scripts in its repo *before* installing — inspecting the files as they are for risky patterns.
- **`csm-skill-update`** runs a **diff analysis** of the *incoming* changes *before* applying an update — so you see what new code an update would introduce, not just the current state.
- **`csm-skill-audit --scan`** runs an on-demand **deep security scan** across *every already-installed* skill — reading each skill's contents and reporting a per-skill and overall **security score** with findings grouped by severity. Run it directly, or accept the prompt offered at the end of a standard audit.

All three consult a shared pattern catalog, [`shared/security-patterns.md`](shared/security-patterns.md), which covers, at a high level:

- **Shell execution** — `subprocess`, `exec`, `eval`, `os.system`, `child_process`, and similar
- **Network activity** — `curl`/`wget`/`fetch` and requests to non-GitHub URLs
- **Credential harvesting** — references to `API_KEY`, `TOKEN`, `~/.ssh`, `~/.aws`, and the like
- **Obfuscation** — base64/hex-encoded strings and other attempts to hide intent
- **Scope expansion** — file writes outside the skill directory, scripts that run automatically (e.g. `.github/` workflows, post-clone hooks), and changes that widen a skill's permissions

**These checks are advisory.** The skills surface findings in plain English and flag anything suspicious, but they never block or modify anything on their own — **you always make the final decision** on whether to install, update, or act on a flagged skill.

## Repository layout

```
ClaudeSkillManager/
├── install.sh                # one-shot POSIX installer (clone + symlinks)
├── shared/
│   └── security-patterns.md  # shared catalog for the install + update scans
├── csm-skill-install/
│   └── SKILL.md
├── csm-skill-update/
│   ├── SKILL.md
│   └── scripts/
├── csm-skill-finder/
│   ├── SKILL.md
│   └── references/           # incl. upstream-baseline.md for drift detection
└── csm-skill-audit/
    ├── SKILL.md
    └── scripts/              # audit.py (read-only health scan, + --scan security scan → JSON)
```
