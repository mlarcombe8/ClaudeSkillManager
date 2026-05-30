# ClaudeSkillManager

A suite of [Claude Code](https://claude.com/claude-code) skills for installing, updating, and auditing skills **properly** — that is, with a real git connection back to each skill's source so it can be reviewed, updated, and rolled back over time.

## Why git-connected installs matter

When a skill is installed by a plain file copy or download, it lives on your machine but has no link to its origin on GitHub. That means you can't check for updates, can't see what changed between versions, and can't roll back if an update breaks something. The skills in this suite install each skill as a git clone with a remote, so all of that becomes possible.

## Requirements

The installer and manual install steps below are **POSIX shell** — they work in:

- **macOS** and **Linux** out of the box.
- **Windows via WSL** (which is Linux under the hood).
- **Windows via Git Bash / Cygwin / MSYS2** — should work, with one caveat: the suite relies on real symlinks (`ln -s`) to activate each skill, and on Windows that requires **Developer Mode** or admin. Without it, `ln -s` either fails or silently falls back to a copy, and Claude Code may not load the skill correctly.

**Native Windows (CMD / PowerShell) isn't supported as-is** — no POSIX `sh`, no `ln -s`, no `mkdir -p`. Use WSL instead.

You'll also need `git` and `curl` (for the quick install), plus [Claude Code](https://claude.com/claude-code) itself.

## Quick install

```sh
curl -fsSL https://raw.githubusercontent.com/mlarcombe8/ClaudeSkillManager/main/install.sh | sh
```

This clones the suite and symlinks its six skills into `~/.claude/skills`. **Why a clone instead of a copy?** Installing as a `git clone` keeps a live remote back to GitHub, so the skills stay **updatable**, **rollback-able**, and **auditable** over time — none of which is possible with a plain file copy or `npx skills add`.

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
| [`csm-skill-audit`](csm-skill-audit/) | Audits your whole skill library and reports a health score with findings grouped by severity (broken symlinks, no git remote, behind on updates, drift, orphaned files). Also offers a **deep security scan** (`--scan`) that analyzes each skill's contents for risky behavior, and an inventory mode (`--list`) that just lists what's installed. Read-only — it hands off fixes to `csm-skill-install`/`csm-skill-update`. |
| [`csm-skill-rollback`](csm-skill-rollback/) | Rolls an installed skill back to a previous version. Lists rollback points (git history), shows a diff, and security-checks the target version before applying, then rolls back via git. Works for skills installed *or* updated by the suite. Invoke as `/csm-skill-rollback <skill>`. |
| [`csm-skill-remove`](csm-skill-remove/) | Removes an installed skill thoroughly: the symlink, and (when safe) its backing git clone. Detects multi-skill bundles so it never orphans siblings, takes a backup before deleting, double-confirms when removing a suite skill itself, and logs the result. Invoke as `/csm-skill-remove <skill>`. |

## Scope — user-global vs project-scoped

Claude Code supports two scopes for installed skills, and the suite is aware of both:

| Scope | Symlink lives at | When it's loaded |
| --- | --- | --- |
| **`user`** *(default)* | `~/.claude/skills/<name>` | Every Claude Code session, anywhere |
| **`project`** | `<project_root>/.claude/skills/<name>` | Only when launched inside that project tree |

**`csm-skill-install` resolves scope automatically** based on how you invoke it:

| Invocation | Behavior |
| --- | --- |
| `/csm-skill-install <repo>` *(no flag)* | Defaults to **user-global**. If you're inside a project (cwd has a `.claude/skills/` ancestor), it asks first via a quick prompt — *user-global*, *this project*, or *a different project…* (which opens a picker). |
| `/csm-skill-install <repo> --project` | Installs into the project the current shell is inside (walks up from cwd to find it). If you're not in a project, a picker offers candidates from `~/ClaudeProjects/` that already have a `.claude/skills/` dir, plus a free-text "Other" path option. |
| `/csm-skill-install <repo> --project <path>` | Installs into the specific project at `<path>`, regardless of where you're running from. Expands `~`, resolves relative paths, refuses if it resolves to `$HOME`. |

**The git clone always goes to a shared `~/.agents/skills/<repo_name>/` regardless of scope**, so a single clone can back both user-global and project symlinks — one `git pull` updates everything.

The other commands handle scope transparently: `csm-skill-audit --list` shows each skill's scope, `csm-skill-update` discovers and updates skills at both scopes when run inside a project, and `csm-skill-rollback` / `csm-skill-remove` ask you to disambiguate with `--scope user|project` if a skill happens to be installed at both.

## Security

Several of the skills review skill code for risky behavior, at different moments:

- **`csm-skill-install`** runs a **static analysis** of a skill's `SKILL.md` and any scripts in its repo *before* installing — inspecting the files as they are for risky patterns.
- **`csm-skill-update`** runs a **diff analysis** of the *incoming* changes *before* applying an update — so you see what new code an update would introduce, not just the current state.
- **`csm-skill-audit --scan`** runs an on-demand **deep security scan** across *every already-installed* skill — reading each skill's contents and reporting a per-skill and overall **security score** with findings grouped by severity. Run it directly, or accept the prompt offered at the end of a standard audit.
- **`csm-skill-rollback`** checks the **target version** *before* rolling back — so reverting to an older version can't silently reintroduce a risky pattern that a later version fixed.

These skills consult a shared **pattern catalog**: [`shared/security-patterns.md`](shared/security-patterns.md).

### What the pattern catalog is

A "pattern catalog" is just a structured list of **things to look for in code**. This one is a markdown file that lists concrete identifiers, function calls, and code snippets — for example `subprocess.run(`, `eval(`, `curl`, `~/.ssh`, `process.env.API_KEY`, base64-decoded strings — that the scanners search each skill's source files for. Every entry has a **priority tier** (High / Medium / Low — see the table below) and a category it belongs to.

It's not a blocklist. A match means *"worth a second look,"* not *"definitely malware"* — the skill surfaces every finding in plain English and **you decide** whether to proceed.

### What the catalog flags

The catalog groups its entries into these categories (each one is a *kind of behavior* it has entries for):

- **Shell execution** — code that runs external commands: `subprocess`, `exec`, `eval`, `os.system`, `child_process`, backtick execution, `$()` command substitution. *Why it's flagged:* shell execution lets a skill do anything the user can do at the command line, so any use is worth confirming it matches what the skill is supposed to do.
- **Network activity** — outbound requests: `curl`, `wget`, `fetch()`, `axios`, `requests.get/post`, WebSocket connections, calls to raw IP addresses, requests to non-GitHub URLs. *Why it's flagged:* this is how a skill could quietly exfiltrate data or pull in unreviewed code at runtime.
- **Credential harvesting** — references to credential-bearing locations (`$HOME`, `~/.ssh`, `~/.aws`, `~/.config`, `.env` files) or environment variables that conventionally hold secrets (`API_KEY`, `TOKEN`, `SECRET`, `PASSWORD`). *Why it's flagged:* a malicious skill would read your keys from exactly these places.
- **Obfuscation** — base64/hex-encoded strings decoded at runtime, `eval()` on dynamic strings, minified or single-character variable names in new scripts. *Why it's flagged:* legitimate skills don't hide what their code does; obfuscation usually signals an attempt to evade review.
- **Scope expansion** — file writes outside the skill's own folder (e.g. into `~/.claude/`, `~/.config/`, `/etc/`, `/usr/`), scripts that run automatically (`.github/` workflows, post-clone hooks), removal of confirmation prompts that previously existed, and new auto-apply or auto-execute behaviors. *Why it's flagged:* a skill widening its boundaries — especially mid-update — often means it's doing more than it claims.
- **New external dependencies** — new `import` / `require` statements or new entries in `package.json` / `requirements.txt`. *Why it's flagged:* the new code came from somewhere you haven't reviewed yet.

Each pattern in the catalog carries a **priority tier**, which the scan maps to the severity icons you'll see in its output:

| Tier | Severity in scan | What it means |
| --- | --- | --- |
| High | 🔴 critical | Always flag — these patterns are risky regardless of context |
| Medium | 🟡 warning | Flag with context — judged against what the skill is supposed to do |
| Low | 🔵 info | Note but don't block (e.g. external documentation links) |

A few sanity-checks the scan applies on top of the raw patterns:

- **Documentation / comment matches are demoted to 🔵 info**, so a security-tooling skill that *mentions* `eval` or `subprocess` in its docs doesn't trip a false 🔴.
- **Context-aware judgment** — `git` commands in a git-related skill, `curl` to a well-known docs URL, etc. get rated against the skill's stated purpose rather than treated as automatic criticals.
- **Suite skills are tagged `is_suite_skill: true`** so the audit can contextualize findings inside this suite's own code (the install/update/audit skills legitimately consult these patterns).

### Running the deep security scan

`csm-skill-audit`'s scan is the *already-installed* layer. Trigger it two ways:

- **`/csm-skill-audit --scan`** — run it directly (skips the prompt).
- Accept the prompt offered at the **end of a standard `/csm-skill-audit`** run.

Before reading any content, it shows a **pre-scan summary** so you know the cost up front — one row per skill with its **size** (SKILL.md + scripts), **number of script files**, and an **estimated complexity** (🟢 low / 🟡 medium / 🔴 high, derived from file count and total size), plus totals:

```
  Skill              Size       Scripts   Complexity
  ───────────────────────────────────────────────────
  impeccable         854.0 KB   40        🔴 high
  ui-ux-pro-max      128.6 KB    4        🟡 medium
  brandkit            15.6 KB    0        🟢 low
  Total: 19 skills · 65 files · 1.3 MB
```

It then shows a usage warning:

> ⚠️ Note: A full library scan reads and analyzes every skill file and may consume significant Claude usage. For large libraries consider scanning individual skills instead. You can always run a targeted scan later with /csm-skill-audit --scan and select specific skills at that time.

…and offers **three choices** (not just yes/no):

1. **Scan all skills**
2. **Select specific skills to scan** — pick from the list above
3. **Skip for now**

To scan only certain skills without the picker, name them directly:

```sh
/csm-skill-audit --scan --skills impeccable,ui-ux-pro-max
```

Each scanned skill gets a **per-skill security score** and the library gets an **overall score**, with findings grouped 🔴 critical / 🟡 warning / 🔵 info. Flagged skills are handed off to `/csm-skill-update` (if an update is pending) or `/csm-skill-install` (to reinstall cleanly).

**These checks are advisory.** The skills surface findings in plain English and flag anything suspicious, but they never block or modify anything on their own — **you always make the final decision** on whether to install, update, or act on a flagged skill.

## Activity log

Every install, update, and audit/scan appends a line to a local **activity log**, so you — and `csm-skill-audit` — can see what the suite has done over time.

- **Location:** `~/.csm/csm.log` (the `~/.csm/` directory is created automatically on first write).
- **Format:** [JSON Lines](https://jsonlines.org/) — one JSON object per line, both human-readable and easy to parse (e.g. `cat ~/.csm/csm.log | jq`).
- **Each entry has:** `timestamp` (ISO 8601), `skill` (install name or `all`), `action` (`installed` / `reinstalled` / `skipped` / `failed` / `checked` / `updated` / `skipped-update` / `audit-run` / `scan-run`), `source` (GitHub URL where relevant), `result` (`success` / `failure` / `up-to-date`), and `details` (a short plain-English summary).
- **Extra structured fields:** some actions attach typed fields so readers never have to parse numbers out of `details` — e.g. a `scan-run` carries `skills_scanned` (and `overall_score`), `checked` carries `updates_available`, and `updated` carries `commits`. Any skill can add fields via `csm_log.py --field NAME=VALUE`.

Example line:

```json
{"timestamp": "2026-05-24T10:30:00-04:00", "skill": "all", "action": "scan-run", "source": "", "result": "success", "skills_scanned": 19, "overall_score": 84, "details": "Security scan of 19 skills; overall 84/100 (B); scope all"}
```

`csm-skill-audit` reads this log and prints a short **Suite Activity** summary — last install, last update check, last security scan, last rollback, last removal — at the top of every audit (or "No activity logged yet" when the log is empty). The log is written by the shared `shared/csm_log.py` helper and lives **outside the repo** in your home directory; the repo's `.gitignore` also excludes `~/.csm`-style paths so a log can never be committed by accident.

## Repository layout

```
ClaudeSkillManager/
├── .gitignore                # ignores ~/.csm logs (and pycache) if they appear in-repo
├── install.sh                # one-shot POSIX installer (clone + symlinks)
├── shared/
│   ├── security-patterns.md  # shared catalog for the install, update & audit scans
│   └── csm_log.py            # shared JSON-lines activity logger (writes ~/.csm/csm.log)
├── csm-skill-install/
│   └── SKILL.md
├── csm-skill-update/
│   ├── SKILL.md
│   └── scripts/              # discover.py (repo-grouped update discovery)
├── csm-skill-finder/
│   ├── SKILL.md
│   └── references/           # incl. upstream-baseline.md for drift detection
├── csm-skill-audit/
│   ├── SKILL.md
│   └── scripts/              # audit.py (health scan, + --scan security scan, + --list inventory → JSON)
├── csm-skill-rollback/
│   ├── SKILL.md
│   └── scripts/              # rollback_points.py (read-only: lists git rollback points)
└── csm-skill-remove/
    ├── SKILL.md
    └── scripts/              # remove_plan.py (read-only: builds a removal plan, JSON)
```
