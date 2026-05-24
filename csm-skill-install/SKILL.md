---
name: csm-skill-install
description: Install Claude Code skills properly via git clone with a remote. Use this skill whenever the user wants to install a new skill, add a skill, get a skill, or set up a skill from GitHub. Also use when a user mentions a skill by name and wants to use it. Trigger on phrases like "install skill", "add skill", "get skill", "install X skill", "set up X".
---

# csm-skill-install

Part of the **ClaudeSkillManager Suite** — a set of skills for installing, updating, and auditing Claude Code skills properly.

---

## About ClaudeSkillManager

ClaudeSkillManager is a suite of skills designed to help you manage your Claude Code skills the right way — installing them with a proper git connection so they can be safely reviewed and updated over time.

**Why "installed properly" matters:**
When a skill is installed via a simple file copy or download tool, it exists on your machine but has no connection back to its source on GitHub. This means:
- You can't check for or apply updates automatically
- You can't see what changed between versions
- You can't roll back if an update breaks something
- Security reviews of updates aren't possible

When a skill is installed properly via `git clone`, it maintains a live connection (called a "remote") back to its GitHub source. This means:
- Updates can be fetched and reviewed before applying
- You can see exactly what changed in any update
- You can roll back to any previous version
- The full suite of ClaudeSkillManager tools can manage it

**The ClaudeSkillManager Suite:**
- **csm-skill-install** *(this skill)* — Installs skills properly via git clone, checks if already installed and whether installed correctly
- **csm-skill-update** — Scans all installed skills for updates, reviews diffs, performs security checks, and applies approved updates
- **csm-skill-finder** — Discovers skills from the open ecosystem and hands off installs to this skill
- **csm-skill-audit** — Audits your entire skill library for health and updatability, plus an optional deep security scan of skill contents
- **csm-skill-rollback** — Rolls an installed skill back to a previous version, showing a diff and a security check of the target first
- *More skills will be added to the suite over time*

**GitHub:** `https://github.com/mlarcombe8/ClaudeSkillManager`

---

## Execution Safety & Shell Portability

**Read this before running any shell command.** Hidden failures and shell-portability bugs can silently corrupt an install. These rules are mandatory.

### Shell portability — do NOT assume bash
The user's default shell is frequently **zsh** (macOS default), and the system `bash` is often **3.2** (no associative arrays). Therefore:
- ❌ Do NOT use `declare -A` or `${!map[@]}` — those are bash-4-only; they fail on macOS bash 3.2 and in zsh.
- ❌ Do NOT rely on unquoted `$var` word-splitting. **zsh does not field-split unquoted parameter expansions**, so `tar -czf out.tgz $NAMES` passes *all* names as a single argument and silently archives nothing.
- ✅ Iterate a fixed list with a heredoc + `read` loop (works in bash 3.2 *and* zsh):
  ```bash
  while read -r name subpath; do
    [ -z "$name" ] && continue
    # ... use "$name" and "$subpath" (always quoted) ...
  done <<'PAIRS'
  install-name-1 subpath-1
  install-name-2 subpath-2
  PAIRS
  ```
  …or pass explicit literal arguments, or a properly-quoted indexed array iterated as `for x in "${arr[@]}"`.

### Never hide errors on state-changing commands
- ❌ Do NOT append `2>/dev/null` to `tar`, `git clone`, `git pull`, `mv`, `rm`, or `ln`. A hidden stderr once produced a **silent empty backup**. Let errors show and check exit codes.

### Backup-before-destroy protocol (mandatory before any `rm -rf` of an existing install)
1. Create the backup: `BK=/tmp/<name>-backup-$(date +%Y%m%d-%H%M%S).tgz; tar -czf "$BK" <dirs...>`
2. **Verify it** — confirm the file is non-empty and lists the expected entries:
   ```bash
   ls -la "$BK"; tar -tzf "$BK" | awk -F/ 'NF>1{print $1}' | sort -u
   ```
3. Only after the backup is confirmed do you `rm -rf` the old install. If the backup is empty/wrong, STOP and fix it first.

### Safe order of operations for a (re)install
**backup → verify backup → clone fresh → verify clone (expected SKILL.md present) → remove old → relink → verify links resolve.**
Always clone and verify *before* removing anything, so a failed clone never leaves the user with nothing.

### Symlinks
- Use `ln -sfn <target> <link>` to create/repoint a symlink idempotently (force + no-dereference). Remove broken symlinks before recreating.
- The **link name** in `~/.claude/skills/` must be the skill's `name:` from its SKILL.md frontmatter — **not** the repo folder name (they often differ, e.g. folder `taste-skill` → `name: design-taste-frontend`).

---

## Workflow

### STEP 1 — Identify the Skill Source

Ask the user for the GitHub URL or skill name if not already provided.

**If the user gives a name or description rather than a GitHub URL, search for matching skills before proceeding:**
- Check `~/.claude/skills/` for a symlink and `~/.agents/skills/` for an existing install.
- Search the open skills ecosystem with the Skills CLI:
  ```bash
  npx skills find <query>
  ```
  Present the matches to the user with each candidate's **install count**, **source/author**, and **GitHub stars**, plus a one-line description, so they can choose the right one. (The chosen skill then gets vetted in STEP 2.5.)
- Also search GitHub directly (`gh search repos "<name>"`, and `gh api users/<author>/repos` if an author was named) and confirm the match by comparing the repo's description/SKILL.md to what was requested.
- **Community validation:** popular, battle-tested skills are ranked by total installs on the **skills.sh leaderboard** (https://skills.sh/). Check it to see whether a well-known skill already covers the user's need.
- If still unknown, ask the user for the GitHub URL.

Confirm the specific skill and its source repo with the user before continuing.

### STEP 2 — Check if Already Installed

Check both skill dirs, and **resolve the real path** — installs are often symlinks into a shared clone, so the repo root may differ from `~/.agents/skills/<skill_name>`:

```bash
ls ~/.claude/skills/ | grep -i <skill_name>
# Resolve the symlink to its physical location (portable; macOS lacks `readlink -f`):
real=$(cd ~/.claude/skills/<skill_name> 2>/dev/null && pwd -P)
[ -z "$real" ] && real=~/.agents/skills/<skill_name>
echo "real path: $real"
# Find the enclosing git repo root (handles nested + multi-skill repos):
git -C "$real" rev-parse --show-toplevel 2>/dev/null && echo "(git-managed)" || echo "(not a git repo)"
```

- If `--show-toplevel` returns a path, the skill is **git-managed**; that path is the repo root. If that repo backs *more than one* installed skill, it's a **multi-skill repo** — see STEP 3.
- **Branch based on result — see decision tree below.**

---

### STEP 2.5 — Reputation & Community Validation

Before installing **any** skill, vet how trustworthy and well-regarded it is, then present your findings to the user. This is a *trust* gate that runs ahead of the code-level **Security Scan in STEP 4** — the two are complementary: reputation tells you whether the author and skill are credible; the STEP 4 scan inspects what the code actually does. Both must pass.

Check and report:
- **Install count** — prefer skills with **1K+ installs**. Treat anything under ~100 installs with caution and say so explicitly.
- **Source reputation** — official / well-known sources (e.g. `vercel-labs`, `anthropics`, `microsoft`) are trustworthy. **Flag unknown or unverified authors.**
- **GitHub stars** — check the source repo and **flag any repo with under 100 stars** as low-signal and worth extra scrutiny.
- **Community validation** — cross-check the **skills.sh leaderboard** (https://skills.sh/), which ranks skills by total installs. Appearing there is a good sign; absence isn't disqualifying but is worth noting.

Gather these from the Skills CLI search output (STEP 1) and/or GitHub:
```bash
gh repo view <owner>/<repo> --json stargazerCount,description,url
```

Present a concise summary, e.g.:
> Reputation check for **<skill>** (`<owner>/<repo>`): 185K installs · source `vercel-labs` (trusted) · 1.2K★ · listed on skills.sh. ✅ Looks reputable.

or, when something is off:
> ⚠️ Reputation check for **<skill>** (`<owner>/<repo>`): ~40 installs · unknown author · 12★ · not on the leaderboard. Low-signal — proceed only if you trust the source.

If any signal is weak, **ask the user whether to continue** before moving on. This validation matters most when an install or reinstall will actually happen (Decision Tree cases B1 and C below); if the skill is already correctly installed (case A), no install occurs and this gate can be skipped.

---

## Decision Tree

### A) Already installed + installed properly (git remote exists)

```bash
root=$(git -C "$real" rev-parse --show-toplevel 2>/dev/null)
[ -n "$root" ] && git -C "$root" remote -v
```

If a remote exists → tell the user:
> "This skill is already installed and set up correctly with a git connection to GitHub. No reinstall needed."

Then **log the skip** (best-effort):
```bash
python3 ~/.claude/skills/csm-skill-install/../shared/csm_log.py \
  --skill <install_name> --action skipped --source <github_url> --result success \
  --details "Already installed correctly (git remote present); no reinstall needed"
```

If the repo is a multi-skill repo, note that the same clone manages its sibling skills too. Offer to update it via csm-skill-update instead.

---

### B) Already installed + NOT installed properly

If no git remote exists → explain to the user:
> "This skill is already installed on your machine, but it was installed without a git connection to its GitHub source. This means it can't be automatically updated, reviewed for changes, or rolled back if something goes wrong. Installing it properly would give you full update and version control."

Then check if it can be fixed:

**B1 — Can be fixed (GitHub source is findable):**

Try to identify the source repo:
- Check if a README or SKILL.md contains a GitHub URL
- Search GitHub for the skill name/author if needed, and confirm by matching the description

If source is found → offer to reinstall properly:
> "I found the original source at [URL]. Would you like me to reinstall this skill properly? Your existing skill files will be replaced with a fresh git clone. Note: if you've made any custom changes to the skill files, those will be lost."

- If **yes** → proceed to STEP 3 (Install). If the source turns out to be a multi-skill repo, follow the multi-skill scope question there.
- If **no** → offer to run csm-skill-update to check for any available updates instead, noting that full update functionality will be limited without a git remote

**B2 — Cannot be fixed (no findable GitHub source):**

Tell the user:
> "This skill is installed but without a git connection, and I wasn't able to find its original GitHub source. This could mean it was created manually, installed from a private repo, or the source repo no longer exists. It cannot be converted to a properly managed install."

Explain what this means practically:
- Updates cannot be automatically checked or applied
- csm-skill-update will flag it as "cannot be auto-updated"
- The skill will still work normally — it just can't be managed by the suite

Offer to run csm-skill-update anyway to confirm its status in the suite.

---

### C) Not installed — proceed with install

Go to STEP 3.

---

## STEP 3 — Identify Repo Structure (single vs multi-skill)

Clone to a temp location and inventory **every** SKILL.md:

```bash
rm -rf /tmp/skill-inspect-temp
git clone <github_url> /tmp/skill-inspect-temp
find /tmp/skill-inspect-temp -name SKILL.md -not -path '*/.git/*'
```

For **each** SKILL.md found, read its frontmatter `name:` and `description:`. **The install name (`name:`) often differs from the folder name** — always track both.

**Single-skill repo** — exactly one SKILL.md (at the root or in one subfolder) → proceed to STEP 4.

**Multi-skill repo** — two or more SKILL.md files in different subfolders. Build a table of `install-name | repo-folder | description`, then **decide scope *with the user* — this question is mandatory; never assume:**

- **If the user named/triggered one specific skill** (e.g. "install the Taste Skill"): identify which subfolder it maps to, then **ASK** which they want:
  1. **Just that skill**,
  2. **A subset** they choose, or
  3. **The whole bundle** (all skills in the repo).

  Always surface the whole-repo option, because a single clone can back every skill in the repo (efficient to install and to keep updated together). Use the `AskUserQuestion` tool for this choice.
- **If the user pointed at the repo/URL generally**: present the full table and ask which skills to install (all / a subset / one).

Also tell the user when any of the repo's skills are **already installed**: resolve existing `~/.claude/skills/*` symlinks (`cd … && pwd -P`) to see whether they already point into this same repo, or exist as separate non-git copies. Offer to convert those non-git copies to the shared git-managed clone in the same operation.

Wait for the selection before proceeding to STEP 4.

---

## STEP 4 — Security Scan

This code-level scan complements the **Reputation & Community Validation (STEP 2.5)**: reputation vets the author and popularity; this scan vets what the code actually does. Run both — a skill can be popular and still ship risky code.

Before installing, read each selected SKILL.md and any scripts in the repo and perform a security review:

**Flag any of the following:**
- Shell execution commands (`subprocess`, `exec`, `eval`, `os.system`, `child_process`)
- Network requests to non-GitHub URLs (`curl`, `wget`, `fetch`)
- File system writes outside the skill directory
- Credential or token references (`API_KEY`, `TOKEN`, `~/.ssh`, `~/.aws`)
- Obfuscated or encoded strings (base64/hex)
- New scripts that run automatically without user confirmation (e.g. CI workflows in `.github/`, post-clone hooks)

Read `../shared/security-patterns.md` for full patterns to check.

Present findings to the user:
- ✅ No security concerns found → proceed
- ⚠️ Concerns found → list them clearly and ask if the user wants to proceed anyway

---

## STEP 5 — Install

Apply the rules in **Execution Safety & Shell Portability** above: no hidden stderr, backup-before-destroy, portable `while read` loops, `ln -sfn`, and clone-before-remove.

**Clone once, symlink the selected skills.** A multi-skill repo is cloned a *single* time; each selected skill becomes a symlink into that one clone, named by its `name:`.

1. **Reuse or create the clone.** If the repo is already cloned at `~/.agents/skills/<repo_name>` (e.g. a sibling skill from the same bundle was installed earlier), do NOT re-clone — reuse it. Otherwise clone fresh and verify the expected SKILL.md(s) exist:
   ```bash
   rm -rf /tmp/skill-inspect-temp
   git clone <github_url> ~/.agents/skills/<repo_name>
   ls ~/.agents/skills/<repo_name>/<subpath>/SKILL.md   # sanity-check each selected skill
   ```
2. **(Only if converting existing non-git copies)** Run the backup-before-destroy protocol and verify the backup *before* removing the old folders.
3. **Link each selected skill** by its install `name:`, pointing at its subpath in the clone. A skill at the repo root uses subpath `.`:
   ```bash
   REPO="$HOME/.agents/skills/<repo_name>"
   while read -r name subpath; do
     [ -z "$name" ] && continue
     target="$REPO/$subpath"
     if [ ! -f "$target/SKILL.md" ]; then echo "ABORT: $target missing SKILL.md"; break; fi
     rm -rf "$HOME/.agents/skills/$name"          # only if an old non-git copy exists there
     ln -sfn "$target" "$HOME/.claude/skills/$name"
     echo "linked: $name -> $subpath"
   done <<'PAIRS'
   <install_name_1> <subpath_1>
   <install_name_2> <subpath_2>
   PAIRS
   ```
   - **Single-skill repo, skill at root:** one line with subpath `.` (links `~/.claude/skills/<name>` to the repo root).
   - **Nested single skill:** subpath like `skills/<folder>`.
   - **Monorepo** (a large project that merely *contains* a skill, e.g. at `.claude/skills/<name>`): cloning it into `~/.agents/skills/<repo_name>` is fine — symlink the nested skill path. The repo root having no top-level SKILL.md is expected.

---

## STEP 6 — Verify

Verify **every** installed/relinked skill, not just one:

```bash
while read -r name; do
  [ -z "$name" ] && continue
  link="$HOME/.claude/skills/$name"
  printf '%-30s -> %s\n' "$name" "$(readlink "$link")"
  grep -m1 '^name:' "$link/SKILL.md" 2>/dev/null || echo "   !! SKILL.md unreadable"
  [ -e "$HOME/.agents/skills/$name" ] && echo "   !! old non-git copy still present at ~/.agents/skills/$name"
done <<'NAMES'
<install_name_1>
<install_name_2>
NAMES
# One git remote backs the shared clone:
cd ~/.agents/skills/<repo_name> && git remote -v && git log -1 --oneline
```

Confirm: each symlink resolves, each `name:` matches its install name, any replaced non-git folders are gone, and the clone has a working `origin` remote. Report results clearly.

Then tell the user:
> "Installation complete. Start a new Claude Code session to use the skill(s). You can run /csm-skill-update at any time to check for updates."

## STEP 7 — Log the outcome

Record what happened (best-effort — logging must never block or fail the install). Use the shared logger, one entry **per skill** you installed/relinked (so a multi-skill bundle logs one line per member):

```bash
python3 ~/.claude/skills/csm-skill-install/../shared/csm_log.py \
  --skill <install_name> --action <installed|reinstalled> \
  --source <github_url> --result success \
  --details "<one-line summary, e.g. 'Installed from <repo>; linked into ~/.claude/skills'>"
```

- Use **`installed`** for a fresh install (Decision Tree **C**).
- Use **`reinstalled`** when you reinstalled an existing or improperly-installed skill (Decision Tree **B1**).

**On failure** — if a clone, backup, link, or verification step fails (see STEP 5 and the Edge Cases), log it instead and report the error to the user:

```bash
python3 ~/.claude/skills/csm-skill-install/../shared/csm_log.py \
  --skill <install_name> --action failed --source <github_url> --result failure \
  --details "<what failed, e.g. 'git clone failed: network error'>"
```

---

## Edge Cases

- **Multi-skill repo, individual request** — always ASK whether to install just the named skill, a subset, or the whole bundle (STEP 3). Never silently install all, and never install only one without offering the bundle.
- **Repo already cloned** — if another skill from the same repo is already git-managed, reuse that clone and just add/repoint a symlink; don't duplicate the clone.
- **Install name ≠ folder name** — the symlink in `~/.claude/skills/` must use the SKILL.md `name:`, not the repo folder name.
- **Shell is zsh / bash 3.2** — see Execution Safety: avoid `declare -A`, `${!arr[@]}`, and unquoted-`$var` word-splitting; never hide stderr on state-changing commands.
- **Backup came out empty** — if `tar -tzf "$BK"` lists nothing, the backup failed (often unquoted-variable word-splitting under zsh, or a wrong cwd). STOP — do not `rm -rf` anything until the backup verifies.
- **Skill name conflict** — if a skill with the same name already exists in `~/.claude/skills/`, warn the user before overwriting.
- **Network failure** — if clone fails, report the error and suggest checking the URL or internet connection.
- **Private repo** — if clone fails due to auth, note that private repos require SSH keys or credentials set up in git.
- **Symlink already exists but points nowhere** — clean up the broken symlink before creating a new one (`ln -sfn` handles repointing).
- **User has customized existing skill files** — warn before replacing; the backup-before-destroy protocol preserves a recoverable copy in `/tmp`.

---

## Reference Files

- `../shared/security-patterns.md` — Security patterns to check during install scan
- `../shared/csm_log.py` — Shared activity logger; called in STEP 7 (and the skip/fail paths) to record `installed` / `reinstalled` / `skipped` / `failed` entries to `~/.csm/csm.log`
