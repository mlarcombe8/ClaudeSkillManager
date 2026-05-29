---
name: csm-skill-remove
description: Remove an installed Claude Code skill thoroughly — the symlink, and (when safe) its backing git clone. Use this skill when the user wants to remove, uninstall, delete, get rid of, or clean up a skill. It detects multi-skill bundles and never orphans sibling skills, takes a backup before deleting, refuses to remove a suite skill without explicit confirmation, and logs the result. Trigger on phrases like "remove <skill>", "uninstall <skill>", "delete <skill>", "get rid of <skill>", "clean up <skill>", or "/csm-skill-remove <skill>".
---

# Skill Remove

You are a skill removal assistant. Your job is to thoroughly uninstall one named skill **without surprises**: detect what removing it actually affects (especially in multi-skill bundles), back up before deleting, confirm with the user, then remove the symlink and — only when safe — the backing git clone.

## About ClaudeSkillManager

ClaudeSkillManager is a suite of skills designed to help you manage your Claude Code skills the right way — installing them with a proper git connection so they can be safely reviewed, updated, rolled back, audited, and removed over time.

**The ClaudeSkillManager Suite:**
- **csm-skill-install** — Installs skills properly via git clone, checks if already installed and whether installed correctly
- **csm-skill-update** — Scans all installed skills for updates, reviews diffs, performs security checks, and applies approved updates
- **csm-skill-finder** — Discovers skills from the open ecosystem and hands off to `/csm-skill-install`
- **csm-skill-audit** — Audits your entire skill library for health and updatability, plus an optional deep security scan; also lists installed skills (`--list`)
- **csm-skill-rollback** — Rolls an installed skill back to a previous version, showing a diff and a security check of the target first
- **csm-skill-remove** *(this skill)* — Removes an installed skill thoroughly (symlink + clone when safe), with multi-skill bundle awareness and a backup before deleting
- *More skills will be added to the suite over time*

**GitHub:** `https://github.com/mlarcombe8/ClaudeSkillManager`

---

## Overview

Removing a skill cleanly is not just `rm ~/.claude/skills/<name>`. A single git clone can back **several** installed skills (a multi-skill bundle like `taste-skill` → `brandkit`/`gpt-taste`/etc.); naively deleting the clone would orphan the siblings. This skill plans the removal carefully and then carries it out.

This skill uses a **hybrid approach**:
1. A Python script (`scripts/remove_plan.py`) resolves the named skill to its symlink + backing clone, finds any sibling skills sharing that clone, flags suite skills, and emits a JSON **removal plan**. **Read-only.**
2. **You (Claude)** interpret the plan, confirm with the user, back up the clone, remove the symlink, and — only when the plan says it's safe — `rm -rf` the clone. Then log it.

---

## Execution Safety

- **Confirm before deleting anything.** Present the plan and what it affects, and get an explicit "yes" before the `rm` step. The user is always in control.
- **Backup-before-destroy.** Before deleting a clone (or removing a whole bundle), `tar -czf` the clone to `/tmp/csm-remove-<name>-backup-<ts>.tgz` and **verify the backup is non-empty** before proceeding (per the suite's standard protocol). Tell the user where the backup is.
- **Never orphan a sibling.** If the clone backs other installed skills (`is_multi_skill: true`), DO NOT delete the clone — only remove this skill's symlink (and optionally the whole bundle, after a separate confirmation).
- **Suite skills are protected.** If `is_suite_skill` is `true` (the skill is part of `ClaudeSkillManager` itself), warn the user clearly that this disables a suite command, and require a **second explicit confirmation** before proceeding. Removing all five suite skills + the clone uninstalls the suite entirely.
- **Don't assume bash 4+ or a specific shell** (zsh / bash 3.2 are common). Avoid `declare -A`, `${!arr[@]}`, and unquoted `$var` word-splitting.
- ❌ **Never append `2>/dev/null`** to `rm`, `tar`, `mv`, `ln`, or `git` — surface errors and check exit codes.

---

## Workflow

### STEP 1 — Identify the skill and build the removal plan

The user names the skill (e.g. `/csm-skill-remove impeccable`). If they didn't, ask which installed skill to remove (suggest `/csm-skill-audit --list` if they're unsure what's installed). Then run:

```bash
python3 ~/.claude/skills/csm-skill-remove/scripts/remove_plan.py <skill-name>
```

The JSON includes `status`, `link_path`, `real_path`, `repo_root`, `is_git`, `has_remote`, `clone_size`, `is_suite_skill`, `is_multi_skill` + `sibling_skills`, and a **`removal_plan`** with `symlink_to_remove`, `clone_to_remove` (or `null`), `bundle_symlinks_to_remove`, `reason_to_keep_clone`, and `needs_backup`.

### STEP 2 — Handle status / edge cases first

Branch on `status`:

| `status` | What it means | What to do |
| --- | --- | --- |
| `not-installed` | No such skill under `~/.claude/skills` (or the current project's `.claude/skills`) | Tell the user; suggest `/csm-skill-audit --list`. Stop. |
| `multiple-scopes` | Skill is installed at **both** user-global and project scope | Ask the user which they meant (use `AskUserQuestion` with `alternative_scopes` as options), then re-run `remove_plan.py <skill> --scope <user\|project>` and continue. |
| `broken-symlink` | A dangling symlink — target gone | Easy case: just `rm` the link. Confirm briefly, do it, log it (STEP 7). No backup needed (nothing else to clean up). |
| `ok` | Installed and resolvable | Continue. The chosen scope is in `scope`; surface it when describing what will be removed ("removing the *user-global* `<skill>` symlink…"). |

### STEP 2b — Suite-skill protection (DOUBLE confirmation)

If `is_suite_skill: true`, warn clearly and ask twice:

> "`<skill>` is part of the **ClaudeSkillManager suite** itself — removing it disables the `/<skill>` command in your library. You can reinstall it later with `/csm-skill-install https://github.com/mlarcombe8/ClaudeSkillManager`. Are you sure?"

Use `AskUserQuestion` for the first answer; if yes, ask a **second** confirmation before continuing. Only proceed if the user explicitly confirms both times.

### STEP 3 — Decide the scope (multi-skill bundle ASK)

If `is_multi_skill: true`, the clone backs other installed skills (`sibling_skills`). Removing the clone would orphan them, so it's a **mandatory ask** (`AskUserQuestion`):

> "`<skill>` shares its clone with: `<sibling_skills>`. Removing the clone would orphan those siblings. How do you want to proceed?"

- **Just unlink this skill** — remove only `~/.claude/skills/<skill>`; leave the clone (and siblings) alone.
- **Remove the whole bundle** — remove this skill's symlink **and** every sibling's symlink **and** the clone. (Strong: it uninstalls every member.)
- **Cancel** — change nothing.

Otherwise (single-skill clone, or non-git directly-installed skill), present the plan plainly:

> "I'll remove `~/.claude/skills/<skill>` and (if applicable) its clone at `<repo_root>` (`<clone_size>`). Proceed?"

### STEP 4 — Back up before destroying (when the plan deletes a clone)

If `removal_plan.needs_backup` is `true` and a clone will be deleted (single-skill case **or** whole-bundle case), back it up first and verify:

```bash
BK=/tmp/csm-remove-<skill>-backup-$(date +%Y%m%d-%H%M%S).tgz
tar -czf "$BK" "<repo_root>"
ls -la "$BK"
tar -tzf "$BK" | awk -F/ 'NF>1{print $1}' | sort -u
```

If the backup is empty or wrong, **STOP** — don't `rm -rf` anything until the backup verifies. Report the backup path to the user.

### STEP 5 — Perform the removal

Run the steps required by the plan, in this order, surfacing any errors:

Use the **actual `link_path`s the plan reports** — `removal_plan.symlink_to_remove` for the named skill (already at the correct scope, user or project), and each entry in `bundle_symlinks_to_remove` is `{install_name, scope}` so the right path is `~/.claude/skills/<install_name>` for `scope: user` and `<project_root>/.claude/skills/<install_name>` for `scope: project`. Don't hardcode `~/.claude/skills` — that's wrong for project-scoped members.

```bash
# 1. Whole-bundle case: remove every sibling symlink too. Compute each
#    sibling's path from its scope (user vs project).
#    bundle_symlinks_to_remove is [{install_name, scope}, ...]
while read -r sib_name sib_scope; do
  [ -z "$sib_name" ] && continue
  if [ "$sib_scope" = "project" ]; then
    rm "<project_root>/.claude/skills/$sib_name"
  else
    rm "$HOME/.claude/skills/$sib_name"
  fi
done <<'SIBS'
<sib_install_name_1> <sib_scope_1>
<sib_install_name_2> <sib_scope_2>
SIBS

# 2. Always: remove the named skill's symlink (or directly-installed dir),
#    using the exact path the plan reported.
rm -rf "<removal_plan.symlink_to_remove>"

# 3. Only if removal_plan.clone_to_remove is non-null (single-skill clone OR
#    whole-bundle case): delete the backing clone.
rm -rf "<clone_to_remove>"
```

Notes:
- For a **non-git, directly installed** skill (a real dir at the link path), step 2 (`rm -rf` the dir) is the whole removal — no clone exists. The plan reflects this with `clone_to_remove: null`.
- Never use `2>/dev/null` here — surface errors.

### STEP 6 — Verify

Confirm what's gone:

```bash
ls -la "$HOME/.claude/skills/<skill>" 2>&1 | tail -1   # should report "No such file"
[ -d "<clone_to_remove>" ] && echo "!! clone still present" || echo "clone removed"
```

For a whole-bundle removal, verify each sibling symlink is also gone. Then tell the user:

> "Removed `<skill>` (and `<siblings>` if bundle). Backup at `<backup-path>` (you can delete it whenever). To bring it back, run `/csm-skill-install <github_url>`. Start a new Claude Code session for the change to take effect."

If anything fails, restore from the backup (`tar -xzf "$BK" -C /`) and report.

### STEP 7 — Log the removal

Record it with the shared logger (best-effort — never block on logging). Use the **`uninstalled`** action and structured `--field`s so the audit's Suite Activity reads them directly:

```bash
python3 ~/.claude/skills/csm-skill-remove/../shared/csm_log.py \
  --skill <skill> --action uninstalled --source <remote_url> --result success \
  --field scope=<user|project> --field clone_removed=<true|false> --field bundle_removed=<true|false> \
  $( [ "<scope>" = "project" ] && printf -- '--field project_root=%q ' "<project_root>" ) \
  --details "Removed <skill>; <symlink only | clone too | whole bundle (<siblings>)>; backup: <backup-path or 'n/a'>"
```

- On failure (any step errored, especially after a partial removal), log `--result failure` with details of what failed and what was restored from backup.
- If the user cancels before STEP 4, change nothing and **don't log**.

`/csm-skill-audit` reads `~/.csm/csm.log` and will surface this as the **Last removal** line in its Suite Activity header.

---

## Edge Cases

- **Skill not installed** — `status: not-installed`; never guess at a path. Suggest `/csm-skill-audit --list`.
- **Broken symlink** — `status: broken-symlink`; `rm` the link, log it, done. No backup needed (nothing else to clean up).
- **Multi-skill bundle** — `is_multi_skill: true`; the clone is shared. Default to removing just the symlink. The "whole bundle" option must be a deliberate, separate confirmation.
- **Suite skill** — `is_suite_skill: true`; warn and require *two* confirmations. Reinstall path is `/csm-skill-install https://github.com/mlarcombe8/ClaudeSkillManager`.
- **Non-git skill** (npx / manual copy / directly-installed dir) — no clone to delete; remove the symlink/dir only. `removal_plan.clone_to_remove` will be `null`.
- **No git remote** — does not block removal, but mention the user won't be able to re-install via `git clone` from a remote URL.
- **Uncommitted local changes** in a clone you're about to delete — the user may have edited files in place. Mention it (`git -C <repo_root> status --porcelain`); the backup tar captures them either way.
- **Removing the clone behind multiple skills** — explicitly disallowed without the "whole bundle" path; the plan never sets `clone_to_remove` to a multi-skill repo by default.

---

## Reference Files

- `scripts/remove_plan.py` — Read-only resolver: maps a skill to its symlink + clone, finds sibling skills sharing the clone, flags suite skills, and emits a JSON `removal_plan` with edge-case `status`.
- `../shared/csm_log.py` — Shared activity logger; called in STEP 7 to record the `uninstalled` entry to `~/.csm/csm.log`.
