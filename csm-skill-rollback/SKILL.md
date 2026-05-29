---
name: csm-skill-rollback
description: Roll an installed Claude Code skill back to a previous version. Use this skill when the user wants to roll back, revert, downgrade, or undo an update to a skill, return a skill to an earlier version, or recover from a bad update. It lists available rollback points (git history), shows a diff and runs a security check on the target version before applying, then rolls back via git. Trigger on phrases like "roll back <skill>", "revert <skill>", "undo the update to <skill>", "go back to a previous version of <skill>", "downgrade <skill>", or "/csm-skill-rollback <skill>".
---

# Skill Rollback

You are a skill rollback assistant. Your job is to take one installed skill back to a previous version **safely**: show what will change, security-check the target version, and only then roll back — with the user's explicit go-ahead at each gate.

## About ClaudeSkillManager

ClaudeSkillManager is a suite of skills designed to help you manage your Claude Code skills the right way — installing them with a proper git connection so they can be safely reviewed, updated, and rolled back over time.

**The ClaudeSkillManager Suite:**
- **csm-skill-install** — Installs skills properly via git clone, checks if already installed and whether installed correctly
- **csm-skill-update** — Scans all installed skills for updates, reviews diffs, performs security checks, and applies approved updates
- **csm-skill-finder** — Discovers skills from the open ecosystem and hands off to `/csm-skill-install`
- **csm-skill-audit** — Audits your entire skill library for health and updatability, plus an optional deep security scan of skill contents; also lists installed skills (`--list`)
- **csm-skill-rollback** *(this skill)* — Rolls an installed skill back to a previous version, showing a diff and a security check of the target first
- **csm-skill-remove** — Removes an installed skill thoroughly (symlink + clone when safe), with multi-skill bundle awareness and a backup before deleting
- *More skills will be added to the suite over time*

**GitHub:** `https://github.com/mlarcombe8/ClaudeSkillManager`

---

## Overview

A rollback works because the suite installs every skill as a **git clone with history** — past versions are already in the local repo, so rolling back is moving the skill's repo to an earlier commit. This skill works for skills installed via **`/csm-skill-install`** *and* skills updated via **`/csm-skill-update`** — both leave a normal git clone whose history is the set of rollback points.

This skill uses a **hybrid approach** (like the rest of the suite):
1. A Python script (`scripts/rollback_points.py`) resolves the named skill to its backing repo and lists the candidate rollback points (git history) — **read-only**, offline (rollback targets are local history).
2. **You (Claude)** interpret that, show the diff, security-check the target version against `../shared/security-patterns.md`, confirm with the user, perform the rollback with git, and log it.

Rollback targets come from **local** history, so no fetch is needed. Rolling *forward* again afterwards is just `/csm-skill-update`.

---

## Execution Safety

- **Confirm before changing anything.** Present the rollback points, the diff, and the security review, and get an explicit yes before the git step. The user is always in control.
- **Never clobber uncommitted work.** Before the rollback, run `git -C <repo> status --porcelain`; if it's non-empty, STOP and tell the user to stash/commit/back up first — a rollback would overwrite their edits.
- **Rolling back is reversible.** The rollback moves the branch pointer; the newer commits still exist on `origin` (and in `git reflog`), so the user can roll forward again with `/csm-skill-update` or by re-checking out the newer commit. Tell them this.
- **Multi-skill repos roll back together.** A single git repo can back several installed skills. The rollback resets the **whole repo**, so every skill it backs moves to the older version — this is a *mandatory* confirmation (see STEP 2b).
- Don't assume bash 4+ or a specific shell (the user's shell may be zsh, system bash may be 3.2). Avoid `declare -A`, `${!arr[@]}`, and unquoted `$var` word-splitting.
- ❌ Never append `2>/dev/null` to `git checkout`, `git reset`, or other state-changing commands — surface errors and check exit codes.
- Run all git commands against the **repo root** reported by `rollback_points.py` (`repo_root`), never against the `~/.claude/skills/` symlink.

---

## Workflow

### STEP 1 — Identify the skill and list rollback points

The user names the skill (e.g. `/csm-skill-rollback impeccable`). If they didn't, ask which installed skill to roll back. Then run:

```bash
python3 ~/.claude/skills/csm-skill-rollback/scripts/rollback_points.py <skill-name>
```

It prints JSON with `status`, the resolved `repo_root` / `subpath` / `branch`, `current_commit`, `is_multi_skill` + `sibling_skills`, and `points` (candidate rollback targets, newest first, with `is_current` marking the live version). Parse it; don't dump raw JSON unless asked.

### STEP 2 — Handle status / edge cases first

Branch on `status` before going further:

| `status` | What it means | What to do |
| --- | --- | --- |
| `not-installed` | No such skill under `~/.claude/skills` | Tell the user; suggest `/csm-skill-audit` to see what's installed, or `/csm-skill-finder` to find one. Stop. |
| `broken-symlink` | The skill link points nowhere | Report it; hand off to **`/csm-skill-install`** to reinstall. Stop. |
| `not-git` | Installed without a git repo (e.g. `npx`/manual copy) | Explain there's **no version history to roll back to**; hand off to **`/csm-skill-install`** to make it git-managed. Stop. |
| `no-history` | Git-managed but only one version exists | Tell the user there's no earlier version to roll back to. Stop. |
| `ok` | Rollback points exist | Continue. |

Also: if `has_remote` is `false`, note that rolling *forward* again later won't be possible via `/csm-skill-update` (no remote to pull from) — the rollback itself still works.

### STEP 2b — Multi-skill repo (MANDATORY ASK)

If `is_multi_skill` is `true`, you **must** confirm before continuing — the rollback resets the whole repo, so the `sibling_skills` roll back too. Use `AskUserQuestion`:

> "`<skill>` shares the repo `<repo_root>` with: `<sibling_skills>`. Rolling back moves the **whole repo** to the older version, so **all of these roll back together** — they can't be rolled back individually. How do you want to proceed?"

- **Roll back the whole repo** (all member skills) — the only way; proceed.
- **Cancel** — stop, change nothing.

### STEP 3 — Present the rollback points and pick a target

Show the points as a readable list (newest first), marking the current version, e.g.:

```
Rollback points for impeccable (repo: impeccable @ main)
  →  e530604  2026-05-24  Make logged counts structured fields   ← current
     5580ae0  2026-05-24  Add JSON-lines activity logging
     41fcc04  2026-05-24  Add pre-scan summary and scoped scanning
     fa6ed4c  2026-05-24  Add deep security scan mode
```

Ask the user which commit to roll back to (`AskUserQuestion`, or let them give a short sha). Call the chosen one `<target>`; the live one is `current_commit`.

### STEP 4 — Show the diff (what will change)

Show what rolling back to `<target>` changes, **at the repo root**, scoped to the skill and (for multi-skill repos) the whole repo:

```bash
# What changes for THIS skill (current → target):
git -C <repo_root> diff <current_sha>..<target> -- <subpath>
git -C <repo_root> diff --stat <current_sha>..<target> -- <subpath>

# For a multi-skill repo, also show the whole-repo impact (siblings move too):
git -C <repo_root> diff --stat <current_sha>..<target>
```

Summarize in plain English: what reverts, what's removed/restored, and — for multi-skill repos — which sibling skills are affected. Remember the diff direction: rolling back *undoes* the changes made after `<target>`.

### STEP 5 — Security-check the target version

Before applying, inspect the **target version's** content (read-only, without touching the working tree) and review it against the shared catalog `../shared/security-patterns.md` — the same one `csm-skill-install` and `csm-skill-update` use:

```bash
# Files present in the target version of this skill:
git -C <repo_root> ls-tree -r --name-only <target> -- <subpath>
# Read the target version of its SKILL.md and any scripts:
git -C <repo_root> show <target>:<subpath>/SKILL.md
git -C <repo_root> show <target>:<subpath>/scripts/<file>
```

Flag anything in the catalog's categories (shell execution on untrusted input, network calls, credential/secret access, obfuscation, scope/permission expansion). Note that rolling back can *reintroduce* an issue that a later version fixed — call that out if you see it. Present findings:
- ✅ No concerns → proceed to confirm.
- ⚠️ Concerns → list them clearly and ask whether to roll back anyway.

### STEP 6 — Confirm, then perform the rollback

Get an explicit final confirmation, then run at the **repo root**. First refuse to clobber local changes, record where you are (so it's reversible), then move the branch back:

```bash
REPO="<repo_root>"; BR="<branch>"; TARGET="<target>"

# 1. Refuse to overwrite uncommitted local edits:
git -C "$REPO" status --porcelain
#    If this prints anything, STOP — have the user stash/commit/back up first.

# 2. Record the current commit so the rollback can be undone:
git -C "$REPO" rev-parse HEAD        # this is the "from" sha — keep it

# 3. Roll the branch back to the target (stays ON the branch — no detached HEAD,
#    so /csm-skill-update can later bring it forward again):
git -C "$REPO" checkout -B "$BR" "$TARGET"

# 4. Verify:
git -C "$REPO" log -1 --oneline
ls "$REPO/<subpath>/SKILL.md"
```

Then tell the user:
> "Rolled `<skill>` back to `<target short>` (<target subject>). Start a new Claude Code session for the change to take effect. To roll forward again later, run /csm-skill-update (or I can return it to `<from short>`)."

If the git step fails, report the error and **log a failure** (STEP 7). Do not force or improvise destructive recovery.

### STEP 7 — Log the rollback

Record it with the shared logger (best-effort — never block on logging). Use the **`rolled-back`** action and structured `--field`s for the commits:

```bash
python3 ~/.claude/skills/csm-skill-rollback/../shared/csm_log.py \
  --skill <skill> --action rolled-back --source <remote_url> --result success \
  --field from_commit=<from_short> --field to_commit=<target_short> \
  --details "Rolled back from <from_short> to <target_short> (<target subject>)"
```

- On failure, log the same action with `--result failure` and a `--details` describing what went wrong.
- For a multi-skill repo, mention the affected siblings in `--details`.
- If the user cancels before STEP 6, change nothing and don't log.

`/csm-skill-audit` reads `~/.csm/csm.log` and will surface this as the **Last rollback** line in its Suite Activity header.

---

## Edge Cases

- **Skill not installed** — `status: not-installed`; suggest `/csm-skill-audit` or `/csm-skill-finder`. Never guess at a path.
- **Broken symlink** — `status: broken-symlink`; the link target is gone — hand off to `/csm-skill-install`.
- **Not git-managed** (`npx`/manual copy) — `status: not-git`; no history exists. Offer `/csm-skill-install` to convert it to a git-managed clone (then future versions become rollback-able).
- **No previous versions** — `status: no-history`; only one commit. Nothing to roll back to.
- **No git remote** (`has_remote: false`) — rollback works, but rolling *forward* again won't (nothing to pull). Warn before proceeding.
- **Multi-skill repo** — rollback is whole-repo; siblings roll back too. Always confirm (STEP 2b) and show the whole-repo diff (STEP 4).
- **Uncommitted local changes** — `git status --porcelain` is non-empty; STOP before the git step so the user's edits aren't overwritten.
- **User edited skill files in place** — those edits are the uncommitted changes above; preserve them (stash/back up) before rolling back.
- **Target equals current** — if the user picks the `is_current` commit, there's nothing to do; say so.

---

## Reference Files

- `scripts/rollback_points.py` — Read-only resolver/lister: maps a skill to its repo and emits the rollback points (git history) plus edge-case `status`.
- `../shared/security-patterns.md` — The suite's shared catalog of risky patterns; used in STEP 5 to vet the target version (shared with `csm-skill-install` and `csm-skill-update`).
- `../shared/csm_log.py` — Shared activity logger; called in STEP 7 to record the `rolled-back` entry to `~/.csm/csm.log`.
