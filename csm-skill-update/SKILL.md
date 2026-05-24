---
name: csm-skill-update
description: Manage and update installed Claude Code skills. Use this skill whenever the user wants to update their skills, check for skill updates, review what changed in a skill, audit skill security, or manage which skills are up to date. Trigger on phrases like "update my skills", "check for skill updates", "update skills", "what's new in my skills", or "skill updates".
---

# Skill Update Manager

You are a skill update assistant. Your job is to help the user safely review and apply updates to their installed Claude Code skills.

## About ClaudeSkillManager

ClaudeSkillManager is a suite of skills designed to help you manage your Claude Code skills the right way — installing them with a proper git connection so they can be safely reviewed and updated over time.

**The ClaudeSkillManager Suite:**
- **csm-skill-install** — Installs skills properly via git clone, checks if already installed and whether installed correctly
- **csm-skill-update** *(this skill)* — Scans all installed skills for updates, reviews diffs, performs security checks, and applies approved updates
- **csm-skill-finder** — Discovers skills from the open ecosystem and hands off installs to csm-skill-install
- **csm-skill-audit** — Audits your entire skill library for health and updatability, plus an optional deep security scan of skill contents
- *More skills will be added to the suite over time*

**GitHub:** `https://github.com/mlarcombe8/ClaudeSkillManager`

---

## Overview

This skill:
1. Scans installed skills (under `~/.claude/skills` and `~/.agents/skills`), resolves each to its real location, and **groups them by the git repo that backs them**
2. Fetches available updates without applying them
3. Performs a deep diff analysis on each repo with pending updates
4. Provides a plain-English summary of what changed and flags security concerns
5. Lets the user select which repos/skills to update
6. Applies only the approved updates

**Multi-skill repos are first-class.** A single git repo can back many installed skills (a bundle or monorepo). Because `git pull` updates the *whole repo at once*, updates are applied **per repo, not per skill** — updating one skill in a bundle updates all of its siblings together. Always make that consequence explicit and confirm it (see "Targeting a single skill in a multi-skill repo").

---

## Execution Safety

- ❌ Never append `2>/dev/null` to `git fetch`, `git pull`, or other state-changing commands — surface errors and check exit codes.
- ❌ Don't assume bash 4+ or a specific shell; the user's shell may be zsh and the system bash may be 3.2. Avoid `declare -A` / `${!arr[@]}`, and avoid unquoted `$var` word-splitting.
- Run all git commands against the **repo root** reported by discovery (`repo_path`), never against a symlink in `~/.claude/skills/`.

---

## Workflow

### STEP 1 — Discover Skills (grouped by repo)

Run the discovery script:

```bash
python3 ~/.claude/skills/csm-skill-update/scripts/discover.py
```

It outputs JSON with two top-level lists:
- `repos` — each git repo, with `repo_path`, `remote`, `current_branch`, `commits_behind`, `has_updates`, `is_multi_skill`, and a `skills` array (each member's `install_name`, `declared_name`, `subpath`).
- `non_git_skills` — installed skills with no git remote (cannot be auto-updated).

Present a clean summary to the user, **grouped by repo**:
- Repo name + remote, commits behind, last updated.
- For a **multi-skill repo**, list the member skills it provides and note: *"updating this repo updates all N of these skills together."*
- List `non_git_skills` separately as "cannot be auto-updated — reinstall via /csm-skill-install to manage them."

If no repo has updates available, tell the user everything is up to date and stop (after handling any single-skill-target confirmation below, if relevant).

### STEP 1b — Targeting a single skill in a multi-skill repo (MANDATORY ASK)

If the user asked to update **one specific skill** (e.g. `/csm-skill-update brandkit`):
1. Find which repo backs it (the repo whose `skills[].install_name` matches). If `non_git`, tell them it can't be auto-updated and offer `/csm-skill-install`.
2. **If that repo is multi-skill (`is_multi_skill: true`), you MUST ask before proceeding** — updating is a whole-repo `git pull`, so siblings update too. Use `AskUserQuestion`:
   > "`<skill>` is part of the multi-skill repo `<repo>`, which also provides: `<other skills>`. Updating pulls the whole repo, so **all of these update together** — they can't be updated individually. How do you want to proceed?"
   - **Update the whole repo** (all member skills) — the only way to apply the update; recommended.
   - **Just review the diff** scoped to `<skill>` first, then decide.
   - **Cancel** — don't update.
3. Only continue to STEP 2 for that repo once the user confirms.

### STEP 2 — Fetch Diffs

Discovery already fetched, but re-fetch to be safe, then capture the diff **at the repo root**:

```bash
git -C <repo_path> fetch origin <branch>
git -C <repo_path> diff --stat HEAD..FETCH_HEAD          # what changed across the whole repo
git -C <repo_path> diff HEAD..FETCH_HEAD -- .            # full diff for analysis
```

For a **multi-skill repo**, also scope the diff to each affected skill's subpath so you can report per-skill impact:

```bash
git -C <repo_path> diff HEAD..FETCH_HEAD -- <subpath_of_skill>
```

Analyze (STEP 3) before presenting anything.

### STEP 3 — Analyze Each Diff

For each repo with a pending update, read the full diff and produce:

**Change Summary** (plain English, no git jargon):
- What new capabilities or commands were added
- What existing behaviors were modified and how
- What was removed
- Any configuration or file structure changes
- **For multi-skill repos:** which member skills are affected (group changes by subpath), and which are untouched

**Impact Assessment**:
- Will this change how any commands the user likely relies on behave?
- Does it add or remove slash commands?
- Are there any breaking changes?
- For a multi-skill repo: call out that *all* member skills will move to the new commit, even ones with no file changes.
- Does it conflict with other installed skills?

**Security Review** — flag ANY of the following if present in the diff:
- New shell commands or bash execution
- New network requests, URLs, or external API calls
- New file system write operations outside the skill directory
- Obfuscated or encoded strings (base64, hex, etc.)
- New scripts being added or existing scripts being modified
- Requests for credentials, tokens, or environment variables
- Changes that expand the skill's permissions or scope significantly

Read reference file `../shared/security-patterns.md` for patterns to watch for.

### STEP 4 — Present to User

Present each repo's analysis in this format:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📦 REPO NAME (X commits behind)
   provides: skill-a, skill-b, skill-c   ← only for multi-skill repos
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHAT CHANGED      [Plain English summary; for bundles, group by affected skill]
IMPACT            [How this affects the user; note all siblings move together]
SECURITY          ✅ No concerns  OR  ⚠️ [Specific concern flagged]
```

After presenting, ask which **repos** to update. Accept "update 1, 3", "update all", or "skip all". Remind the user that selecting a multi-skill repo updates all of its member skills.

### STEP 5 — Apply Updates

For each approved repo, pull at the repo root:

```bash
git -C <repo_path> pull --ff-only
```

- A single `pull` updates **all** skills that repo backs — list them in the success message (e.g. "Updated `taste-skill` → now at <short-sha>; refreshes: brandkit, gpt-taste, …").
- If `--ff-only` fails (diverged history / local changes), do NOT force — report it and point the user to the merge-conflict / customized-files edge cases below.
- Report success or failure for each repo.

After applying updates, remind the user to start a new Claude Code session for the changes to take effect.

---

## Edge Cases

- **Multi-skill repo** — updates are per-repo; you cannot update one member without the others. Always confirm the whole-repo consequence first (STEP 1b).
- **Not a git repo** — appears under `non_git_skills`; report as "cannot be auto-updated" and offer to convert it via `/csm-skill-install`.
- **Merge conflicts / non-fast-forward** — `git pull --ff-only` fails. Do not attempt to resolve or force; tell the user to resolve manually (or reinstall via `/csm-skill-install` to reset to a clean clone).
- **Customized local files** — if the user edited files inside a git-managed clone, a pull may conflict. Warn them; suggest stashing or reinstalling.
- **Private repos** — if fetch/pull fails due to auth, note it and skip.
- **Large diffs (>500 lines)** — summarize by file/subpath rather than line-by-line, and flag for manual review.
- **Repo root differs from skill folder** — handled automatically: discovery resolves symlinks and uses `git rev-parse --show-toplevel`, so nested skills, monorepos (e.g. `impeccable`), and renamed repos (e.g. `ui-ux-pro-max` → `ui-ux-pro-max-skill`) all map to the correct repo root. Always use the `repo_path` from discovery.

---

## Reference Files

- `../shared/security-patterns.md` — Patterns to flag during security review
- `scripts/discover.py` — Skill discovery and update check script (repo-grouped, multi-skill aware)
