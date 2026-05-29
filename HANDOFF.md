# HANDOFF.md

Snapshot for picking this project up in a new Claude Code session. Read this first; `CLAUDE.md` has the deep conventions reference once you need them.

## TL;DR

**ClaudeSkillManager** is a 6-skill suite for Claude Code CLI that installs, updates, audits, rolls back, and removes other Claude Code skills the *git-connected* way (so they're updatable, rollback-able, and auditable). All six skills are built, tested, committed, pushed, and active. The current focus is a small UX improvement on `csm-skill-install`'s scope-prompt flow — described in the [Next session](#next-session) section below.

## Where it lives

| Thing | Path |
| --- | --- |
| **Working clone** | `~/ClaudeProjects/ClaudeSkillManager/` |
| **Public repo** | https://github.com/mlarcombe8/ClaudeSkillManager (owner `mlarcombe8`, branch `main`) |
| **Active skill symlinks** | `~/.claude/skills/csm-skill-{install,update,finder,audit,rollback,remove}` → the repo's six folders |
| **Activity log** (runtime) | `~/.csm/csm.log` (JSON Lines, created on first write) |
| **Latest commit** | `a522895` *(Make scope a first-class concept)* — confirmed clean on `main` |

If you're picking this up in a new session, the practical thing is to launch Claude Code from `~/ClaudeProjects/ClaudeSkillManager/`.

## The six skills

| Skill | Purpose | Script |
| --- | --- | --- |
| **`csm-skill-install`** | Install a skill via `git clone` with a remote. Reputation + security checks. Handles already-installed / fix-improper-install. Supports `--project` for project-scoped installs. | (no script — inline git in SKILL.md) |
| **`csm-skill-update`** | Find updates (repo-grouped, multi-skill-aware), diff + security-review, apply approved `git pull`s. | `scripts/discover.py` |
| **`csm-skill-finder`** | Discover skills (`npx skills find`, skills.sh leaderboard); hand off installs to `/csm-skill-install`. Forked from upstream `find-skills`. | (no script) |
| **`csm-skill-audit`** | Read-only health audit; `--scan` adds deep security scan of contents; `--list` is inventory mode. Reads `~/.csm/csm.log` for a Suite Activity header. | `scripts/audit.py` |
| **`csm-skill-rollback`** | Roll a skill back: list git history, diff, security-check the target, `git checkout -B`. Stays on-branch so update can roll forward again. | `scripts/rollback_points.py` |
| **`csm-skill-remove`** | Thorough uninstall (symlink + clone when safe). Multi-skill-bundle aware, suite-skill protected, backup-before-destroy. | `scripts/remove_plan.py` |

## Architecture cheat sheet

The mental model in five points:

1. **Hybrid pattern.** Each skill that gathers data has a **read-only Python script** that prints JSON; the SKILL.md is the workflow that runs the script, interprets the JSON, confirms with the user, and takes action. Scripts never modify skills.

2. **Symlink model.** `~/.claude/skills/<name>` is the only path Claude Code reads. It's a symlink into a backing clone, conventionally at `~/.agents/skills/<repo_name>/`, but the suite is **location-independent** — the clone can live anywhere readable (this repo's own clone lives at `~/ClaudeProjects/ClaudeSkillManager/`). Auto-derived orphan scan picks that up.

3. **Multi-skill repos are first-class.** One git repo can back many installed skills (e.g. `taste-skill` backs `brandkit`/`gpt-taste`/etc.; the suite repo itself backs all six `csm-*`). `git pull` / rollback / bundle-remove all operate on the *whole repo*, so siblings update or roll back together. Every command that does whole-repo ops has a **mandatory multi-skill confirmation** — this is intentional, not a bug.

4. **Scope is first-class.** Skills can live at **user-global** (`~/.claude/skills/<name>`) or **project-scoped** (`<project_root>/.claude/skills/<name>`). The clone always sits at `~/.agents/skills/<repo>` regardless of scope, so a single clone can back both kinds of symlinks. Every script auto-detects the project root by walking up from cwd (stopping at `$HOME`) and tags each skill record with `scope` (`user`|`project`) and `project_root`.

5. **Shared infrastructure under `shared/`.** Two pieces, both used by multiple skills:
   - **`security-patterns.md`** — the single catalog of risky behavior; install/update/audit-scan/rollback all consult it.
   - **`csm_log.py`** — JSON-Lines activity logger, best-effort (never raises into the workflow). Skills call it via `~/.claude/skills/<skill>/../shared/csm_log.py`, which resolves through the symlink to the repo's `shared/`.

## Recent decisions and lessons learned

These are non-obvious choices/lessons from how the suite got built. Worth knowing if you're about to change something:

- **Renamed everything `csm-` prefix.** Previously `skill-install` etc.; renamed via `git mv` + sweep of all cross-references. Note `csm-skill-update` dropped `-manager` from the original `skill-update-manager`.
- **The repo moved** out of `~/.agents/skills/ClaudeSkillManager/` into `~/ClaudeProjects/ClaudeSkillManager/` (so it lives in the proper projects dir). That move taught us the suite is genuinely location-independent — the only adjustments were re-pointing the 6 symlinks. `CLAUDE.md` documents this with `<clone-root>` placeholders, deliberately *not* hardcoding `~/ClaudeProjects/` (which is machine-specific). The README/installer still target `~/.agents/skills/ClaudeSkillManager` for end users by default.
- **`csm-skill-finder` is a fork** of upstream `find-skills` with install handoffs rewritten to use `/csm-skill-install` instead of `npx skills add`. The pristine upstream lives at `csm-skill-finder/references/upstream-baseline.md` and is intentionally never edited; audit's drift detection compares against it.
- **Security scanner regex precision matters a lot.** Initial scan flagged ~50 false positives in `impeccable` (JS `regex.exec()` ≠ shell `exec(`), `import subprocess` was treated as invocation, and `process.env` matched a `.env` credential file pattern. Fixed with negative lookbehinds and targeting actual invocations (`subprocess\.(run|call|…)` not bare `\bsubprocess\b`). False-positive history matters — if you're tempted to broaden a pattern, look at the audit.py header comments first.
- **Documentation/comment matches are demoted** (`prose: true` → effective severity `info`) so security tooling and docs don't trip false criticals. Suite skills are also flagged `is_suite_skill` for contextualization.
- **Logged numbers go in structured `--field` extras, not text.** Earlier `audit.py` parsed `skills_scanned` out of the `details` string — now scan-run / checked / updated / audit-run / rolled-back / uninstalled all carry typed fields (`skills_scanned`, `commits`, `updates_available`, `health_score`, etc.). Never parse structured data out of `details` going forward; add a `--field`. `read_activity()` still falls back to text-parsing for old log entries.
- **Orphan scan is auto-extending and false-positive-resistant.** Scan roots = `~/.agents/skills/` *plus* the parent of every repo backing an active skill. A tight clone-shape filter (`.git` + `SKILL.md` in a known layout) keeps adjacent project directories from being flagged. Verified on `LPEWebsite` and other project siblings of `ClaudeSkillManager` in `~/ClaudeProjects/`.
- **The Claude desktop app's Customize → Skills panel is a separate ecosystem** from Claude Code CLI's `~/.claude/skills/` — it's cloud-backed, account-level, only shows `anthropic-skills:` and skills added via its own `+`/`skill-creator` flow. Don't go looking for the suite there. Tracked unresolved in anthropics/claude-code issues #39994, #43095, #50644.
- **Self-application works.** Update/audit/rollback/remove can operate on the suite itself; the suite skills appear as a 6-skill bundle in their own discovery. A single rollback or update moves all six together (mandatory confirm fires). Full self-uninstall is recoverable via the `curl | sh` bootstrap (`install.sh`).

## Key conventions (must-know patterns)

These are the rules that show up everywhere; breaking them creates subtle bugs.

- **`name:` in SKILL.md = symlink name = install name.** Always key off the frontmatter `name:`, not folder names (they often differ).
- **`../shared/<file>` from a SKILL.md** resolves through the symlink to the repo's `shared/` dir (kernel follows symlink, then `..` lands at the repo root). Used for `security-patterns.md` and `csm_log.py`.
- **POSIX `sh` only for `install.sh`.** It passes both `sh -n` and `dash -n`. No bashisms.
- **For any shell in SKILL.md:** don't assume bash 4+, avoid `declare -A` / `${!arr[@]}` / unquoted `$var` word-splitting; **never append `2>/dev/null`** to state-changing commands (`git pull/checkout/reset`, `rm`, `mv`, `ln`, `tar`).
- **Backup-before-destroy** before any `rm -rf` of an existing install; verify the backup with `tar -tzf` before deleting.
- **Logging is best-effort, never raises** into the calling workflow.
- **Multi-skill repos always confirm before whole-repo ops** (update, rollback, full-bundle remove). Three commands enforce this; copy the pattern if you add a new one.
- **`csm-skill-remove` has suite-skill protection** — `is_suite_skill: true` requires a *second* explicit confirmation before removing, because removing a suite skill disables a slash command. Self-uninstall is allowed but gated.
- **Test against a sandbox `HOME`** when touching logging (`HOME=$(mktemp -d) python3 …`) so the real `~/.csm` isn't polluted. The `.gitignore` covers `.csm/`, `*.log`, `__pycache__/`, `*.pyc`, but be careful.

## Scope handling (most recent feature)

The last major build. Every script now does this; the SKILL.md files document it.

- **Detect project root** by walking up from cwd to the nearest dir with `.claude/skills/`, stopping at `$HOME` (`$HOME` itself never counts — that's user-global).
- **Skill records carry `scope` (`user`/`project`) and `project_root`** (null for user). Top-level outputs include `project_root` for the run.
- **Resolving by name (rollback / remove):** check both scopes. If found in both, return `status: "multiple-scopes"` with `alternative_scopes`. The caller (Claude per the SKILL.md) asks the user and re-runs with `--scope user|project`.
- **Install's `--project` flag:** symlink lands at `<project_root>/.claude/skills/<name>` with `mkdir -p` first. Clone unchanged in `~/.agents/skills/<repo>`. Refuses when `cwd == $HOME`.
- **Bundle remove targets per-scope paths** — `bundle_symlinks_to_remove` is `[{install_name, scope}]` so the rm loop computes user vs project paths correctly.
- **Logging gains `scope` and `project_root` structured fields** on install/update/rollback/remove actions.

## <a name="next-session"></a>Next session — what's left

The deferred work the user explicitly named, in priority order:

### 1. Smart scope prompt + explicit `--project <path>` for csm-skill-install

The current install scope UX has two gaps the user wants to close:

- It **never asks** "user-global or project?" — the user has to know to pass `--project`. Should ask when meaningful.
- `--project` is currently a **boolean flag** that auto-detects the project root from `cwd`. The user can't pick a different project; they'd have to `cd` there first. Add a path argument form.

**Proposed behavior** (designed and signed off, not implemented):

| Situation | Behavior |
| --- | --- |
| `--project <path>` passed | Use that exact path as the project root. `mkdir -p <path>/.claude/skills`. Refuse if `<path>` resolves to `$HOME`. |
| `--project` passed (no value) | Same as today — walk up from `cwd`, or treat `cwd` as the project root. |
| **No scope flag** AND **cwd is inside a project** (`.claude/skills/` found by walking up) | **Ask via `AskUserQuestion`**: "Install user-globally (`~/.claude/skills/`) or into this project (`<project_root>`)?" Default user-global if dismissed. |
| No scope flag AND cwd is **not** in a project | Silent user-global (today's behavior — no useful question to ask). |

All implementation is in `csm-skill-install/SKILL.md` — no script changes needed. Update the **Scope** preamble (around line 84) and STEPs 5 / 7 to consume the resolved scope/project_root values.

### 2. Maybe later — project picker

If you want a richer experience: when the user picks "into a project" but cwd isn't in one, offer a small picker (e.g. directories under `~/ClaudeProjects/` that already have `.claude/skills/`, plus a "browse" option). Not asked for; deferred.

### 3. Memory note (if memory matters in the new session)

This session wrote three memory notes under `~/.claude/projects/-Users-michael-ClaudeProjects-LPEWebsite/memory/` — they're scoped to that session's project context and **won't auto-load** in a new session launched from `~/ClaudeProjects/ClaudeSkillManager`. If you want them, hand-copy them or recreate from this `HANDOFF.md` (which captures the same info more comprehensively).

## Quick start for the new session

```bash
cd ~/ClaudeProjects/ClaudeSkillManager
git status               # should be clean on main
git log -1 --oneline     # should show a522895 (or whatever's newer)

# Sanity: all six skills active and resolving
ls -la ~/.claude/skills/ | grep csm-skill

# Sanity: scripts compile
python3 -m py_compile shared/csm_log.py \
  csm-skill-audit/scripts/audit.py \
  csm-skill-update/scripts/discover.py \
  csm-skill-rollback/scripts/rollback_points.py \
  csm-skill-remove/scripts/remove_plan.py

# Sanity: a live --list run
python3 csm-skill-audit/scripts/audit.py --list 2>/dev/null \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['counts']['skills'],'skills,',sorted({s['scope'] for s in d['skills']}))"
# expect: 21+ skills, ['user']
```

If anything in the quick start fails, something has drifted since this handoff — investigate before doing new work.

## Documentation map

When you need depth on something, this is where it lives:

| Topic | File |
| --- | --- |
| Architecture, conventions, adding/renaming a skill | `CLAUDE.md` |
| User-facing install + usage | `README.md` |
| Security pattern catalog (used by 4 skills) | `shared/security-patterns.md` |
| Activity-log writer (best-effort, never raises) | `shared/csm_log.py` |
| Each skill's workflow / decision tree / logging | `<skill>/SKILL.md` |
| This handoff | `HANDOFF.md` *(you are here)* |
