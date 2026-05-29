# CLAUDE.md

Guidance for Claude Code (and other agents) working in this repository.

## What this is

**ClaudeSkillManager** is a suite of Claude Code *skills* for installing, updating, auditing, and rolling back other Claude Code skills **properly** — i.e. as a `git clone` with a live remote, so every installed skill can be updated, rolled back, and security-reviewed over time (unlike a plain copy or `npx skills add`).

- **Public repo:** https://github.com/mlarcombe8/ClaudeSkillManager (owner `mlarcombe8`, default branch `main`).
- **Audience split:** `README.md` is for *users* (install + usage). **This file is for working *on* the suite** — conventions, structure, and how to extend it.

## The skills (all `csm-`-prefixed)

| Skill | Folder | Has script? | Purpose |
| --- | --- | --- | --- |
| `csm-skill-install` | `csm-skill-install/` | no (inline git in SKILL.md) | Install a skill via `git clone` + remote; reputation + security checks; handles already-installed / fix-improper-install. |
| `csm-skill-update` | `csm-skill-update/` | `scripts/discover.py` | Find updates (repo-grouped, multi-skill aware), diff + security-review, apply approved `git pull`s. |
| `csm-skill-finder` | `csm-skill-finder/` | no | Discover skills (`npx skills find`, skills.sh leaderboard); hands off installs to `/csm-skill-install`. A fork of the upstream `find-skills` skill. |
| `csm-skill-audit` | `csm-skill-audit/` | `scripts/audit.py` | Read-only health audit (symlinks/git/drift/orphans) + optional `--scan` deep security scan of contents. |
| `csm-skill-rollback` | `csm-skill-rollback/` | `scripts/rollback_points.py` | Roll a skill back to a previous version: list git history, diff, security-check the target, `git checkout -B`. |

`/csm-skill-install` is the preferred install method across the suite.

## How skills are installed/activated (the symlink model)

- **The suite is location-independent.** It works from wherever the repo is cloned, because skills are activated by *symlinks* under `~/.claude/skills` — that's the only path that has to be fixed. The clone itself can live anywhere: `install.sh`/README put it at `~/.agents/skills/ClaudeSkillManager` (the conventional skills location), while a development checkout can live elsewhere (e.g. under a projects directory).
- Each skill is made active by a symlink: **`~/.claude/skills/<install-name>` → `<clone-root>/<folder>`**. Claude Code loads skills from `~/.claude/skills`.
- **The install name = the symlink name = the `name:` in the skill's `SKILL.md` frontmatter.** Here folder names match install names, but in general they can differ — always key off `name:`.
- **Edit files in the repo (the clone), not through the symlink.** After editing, `git commit` + `git push`. The repo is the source of truth; the symlink just points at it.
- **If you relocate the clone**, re-point every symlink with `ln -sfn <new-clone>/<folder> ~/.claude/skills/<name>`. Nothing else needs changing — the `../shared/` references and the scripts all resolve *relative to the symlink target*, so they follow the clone automatically.
- `install.sh` (POSIX `sh`) automates clone + symlinks; the README documents the one-line `curl | sh` and the manual steps.

### Scope — user-global vs project-scoped

Claude Code supports two skill scopes and the suite is aware of both:

- **`user`** (default) — symlink at `~/.claude/skills/<name>`. Loaded in every session, anywhere.
- **`project`** — symlink at `<project_root>/.claude/skills/<name>`. Only loaded when Claude Code is launched inside that project tree.

**The clone always lives at `~/.agents/skills/<repo_name>/` regardless of scope** (or wherever the maintainer keeps it — only the symlink location varies). One clone can back both user-global and project-scoped symlinks; a single `git pull` updates everything backed by that clone.

How each script handles it:
- `audit.py`/`discover.py` walk up from cwd to detect a project root (first ancestor with `.claude/skills/`, stopping at `$HOME`). When found, they scan it *in addition to* `~/.claude/skills/` and tag each skill record with `scope` (`user`|`project`) and `project_root` (null for user).
- `rollback_points.py` / `remove_plan.py` resolve a named skill at both scopes; if found in both, they return `status: "multiple-scopes"` with `alternative_scopes` and require the caller to re-run with `--scope user|project`.
- `csm-skill-install`'s SKILL.md handles a `--project` flag: clone goes to `~/.agents/skills/<repo>`, symlink goes to `<project_root>/.claude/skills/<name>` (`mkdir -p` first); refuses `--project` when `cwd == $HOME`.
- `csm_log.py` accepts `--field scope=<...>` and `--field project_root=<...>`; install/update/rollback/remove all log these.

## Repository layout

```
ClaudeSkillManager/
├── CLAUDE.md                 # this file
├── README.md                 # user-facing docs (install + usage)
├── .gitignore                # ignores ~/.csm logs, *.log, __pycache__/, *.pyc
├── install.sh                # POSIX one-shot installer (clone + symlinks)
├── shared/
│   ├── security-patterns.md  # single risk-pattern catalog (install/update/audit/rollback)
│   └── csm_log.py            # JSON-lines activity logger → ~/.csm/csm.log
├── csm-skill-install/SKILL.md
├── csm-skill-update/        { SKILL.md, scripts/discover.py }
├── csm-skill-finder/        { SKILL.md, references/upstream-baseline.md }
├── csm-skill-audit/         { SKILL.md, scripts/audit.py }
└── csm-skill-rollback/      { SKILL.md, scripts/rollback_points.py }
```

## Core conventions

### SKILL.md structure
Every skill's `SKILL.md` follows the same shape:
1. **YAML frontmatter** — `name:` (must equal the install/symlink name) and a `description:` written as *"what it does + when to use + Trigger on phrases like …"* (this drives skill selection, so keep triggers specific).
2. **About ClaudeSkillManager** — the shared suite bullet list, with the current skill marked `*(this skill)*`. **When you add/rename a skill, update this list in every skill that has it** (install, update, audit, rollback; `csm-skill-finder` only has a fork note, no list).
3. **Overview / Execution Safety / Workflow (STEP 1, 2, …) / Edge Cases / Reference Files.**

### Hybrid pattern (script + SKILL.md)
Skills that need data gathering use a **read-only Python script that prints JSON to stdout**; the SKILL.md tells Claude to run it, interpret the JSON, present results, and take any action. **Scripts never modify skills** — all state changes (install/pull/checkout/delete) are git/shell commands driven by the SKILL.md, with user confirmation.

### Python scripts (`discover.py`, `audit.py`, `rollback_points.py`)
- **Stdlib-only, Python 3.9-compatible** (tested on 3.9.6 — no `match`, no `X | Y` runtime annotations).
- Shared helper style: `run(cmd, cwd=None)` → `(stdout, stderr, rc)`; `git_toplevel(path)`; `read_declared_name(skill_md)`. Reuse these patterns.
- **Read-only**; surface problems in an `errors` array or a `status` field instead of crashing.
- Resolve installed skills via `~/.claude/skills`, follow symlinks (`os.path.realpath`), and find the backing repo with `git rev-parse --show-toplevel`.
- **Multi-skill repos are first-class:** one git repo can back several installed skills (e.g. `taste-skill`). `git pull`/`checkout` act on the *whole repo*, so update and rollback are **per-repo** — siblings move together. Detect this and **always confirm** before whole-repo operations.

### The `../shared/` reference path
Skills reference shared files as **`~/.claude/skills/<skill>/../shared/<file>`**. This resolves correctly because the kernel follows the symlink first, then `..` lands at the repo root (verified for file reads). Used for `security-patterns.md` and `csm_log.py`. (Inside `SKILL.md` prose, reference it as `../shared/<file>`.)

## Logging system

- **Log file:** `~/.csm/csm.log` (created on first write), **JSON Lines** (one object per line).
- **Writer:** `shared/csm_log.py` — called by skills at the moment an action completes. It is **best-effort: it never raises into the workflow and always exits 0**, so a logging hiccup can't break an install/update/audit/rollback.
- **Standard fields (in order):** `timestamp` (ISO-8601 w/ tz), `skill` (install name or `all`), `action`, `source` (GitHub URL or `""`), `result` (`success`/`failure`/`up-to-date`), `details`.
- **Actions:** `installed`, `reinstalled`, `skipped`, `failed`, `checked`, `updated`, `skipped-update`, `rolled-back`, `audit-run`, `scan-run`. **Add new actions to the `ACTIONS` tuple in `csm_log.py`.**
- **Structured extras:** pass `--field NAME=VALUE` (repeatable). Numeric/boolean values are coerced to real JSON types; reserved names can't clobber standard fields. **Prefer a `--field` over burying a number in `details`** — readers must never parse structured data out of free text. Existing structured fields: `skills_scanned`/`overall_score` (scan-run), `skills_checked`/`updates_available` (checked), `commits` (updated), `health_score` (audit-run), `from_commit`/`to_commit` (rolled-back).
- **Reader:** `csm-skill-audit/scripts/audit.py` → `read_activity()` parses the log and the audit shows a **Suite Activity** header (last install / update check / security scan / rollback). It reads structured fields first and only falls back to text-parsing for old entries.

## Security review

- `shared/security-patterns.md` is the **single shared catalog** (High → critical, Medium → warning, Low → info). All four reviewing skills use it: install (static, pre-install), update (diff, pre-apply), audit `--scan` (content analysis of all installed skills), rollback (target version, pre-checkout).
- `audit.py --scan` implements the catalog as regexes. **Lesson learned — keep patterns precise to avoid false positives:** match real invocations, not mentions (`subprocess\.(run|...)` not bare `subprocess`; lookbehind so JS `.exec()` ≠ shell `exec(`; `(?<![\w.])\.env\b` so `process.env` ≠ a `.env` file). Documentation/comment/string-literal matches are demoted to info (`prose: true`); suite skills are flagged `is_suite_skill`. The scan reports *candidate* findings — final judgment ("untrusted input?") is the model's, per the SKILL.md.

## Safety & portability rules (apply to all shell in SKILL.md / install.sh)

- **Don't assume bash 4+ or a specific shell.** The user's shell may be zsh; system bash may be 3.2. Avoid `declare -A`, `${!arr[@]}`, and unquoted-`$var` word-splitting. `install.sh` must stay POSIX (`sh -n` *and* `dash -n` clean).
- **Never append `2>/dev/null` to state-changing commands** (`git clone/pull/checkout/reset`, `mv`, `rm`, `ln`, `tar`) — surface errors and check exit codes.
- **Backup-before-destroy** before any `rm -rf` of an existing install; verify the backup before deleting.
- Use `ln -sfn` for idempotent (re)linking. Rollback uses `git checkout -B <branch> <target>` (stays on-branch, reversible via `/csm-skill-update`) and refuses to run with uncommitted changes.
- Skills and scripts are **read-only by default**; only act with explicit user confirmation, and never auto-fix from a read-only skill (audit/finder hand off; they don't change anything).

## Working in this repo

- **Commit & push to `main`** after changes (this suite has been developed directly on `main`). Write focused commit messages explaining what + why.
- **Test before committing:** `python3 -m py_compile <script>` for Python; `sh -n install.sh && dash -n install.sh` for the installer. For anything touching `~/.csm`, **test with a sandbox `HOME`** (`HOME=$(mktemp -d) python3 …`) so the real log isn't polluted.
- **Never commit** `__pycache__/`, `*.pyc`, or anything under `~/.csm` (the `.gitignore` covers these; `rm -rf **/__pycache__` if `py_compile` created any).
- **Don't edit `csm-skill-finder/references/upstream-baseline.md`** — it's a frozen snapshot of the upstream `find-skills` skill used for drift detection (audit compares the live `SKILL.md` against it). Drift in this fork is expected.

## Adding or renaming a skill

1. Create `csm-skill-<name>/SKILL.md` (frontmatter + About list + Execution Safety + Workflow + Reference Files). Add a `scripts/` helper only if data-gathering warrants it (follow the read-only/JSON pattern).
2. Reference shared utilities via `../shared/…`; log meaningful actions via `csm_log.py` (add the action to `ACTIONS`).
3. Update the **About suite list in every skill that has one**, the **README** (skills table, Security section, layout tree), and — if it's a logged action surfaced in the audit — `audit.py`'s `read_activity()` + the audit's Suite Activity display.
4. Activate it: `ln -s <clone-root>/csm-skill-<name> ~/.claude/skills/csm-skill-<name>` (a new Claude Code session is required for it to load).
5. Renames are done with `git mv` (preserve history) + a full sweep of cross-references (name fields, `/slash` handoffs, script paths, README, About lists) + re-pointed symlinks.
