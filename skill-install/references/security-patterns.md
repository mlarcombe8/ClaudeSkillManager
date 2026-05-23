# Security Patterns to Flag During Diff Review

When reviewing a skill diff, flag ANY of the following patterns as security concerns.

---

## High Priority — Always Flag

### Shell Execution
- `subprocess`, `exec`, `eval`, `os.system`, `child_process`
- Backtick execution in shell scripts
- `$()` command substitution in new or modified shell scripts
- New `.sh` files being added

### Network Activity
- New URLs (http://, https://) especially non-GitHub domains
- `fetch()`, `curl`, `wget`, `axios`, `requests.get/post`
- WebSocket connections
- Any call to an IP address directly

### Credential / Token Harvesting
- References to `$HOME`, `~/.ssh`, `~/.aws`, `~/.config`
- Reading from environment variables like `API_KEY`, `TOKEN`, `SECRET`, `PASSWORD`
- Any file reads outside the skill's own directory
- References to `.env` files

### File System Writes Outside Skill Directory
- Writing to `~/.claude/`, `~/.config/`, `/etc/`, `/usr/`
- Creating files in user home directory
- Modifying existing files outside skill scope

### Obfuscation
- Base64 encoded strings (`atob`, `btoa`, base64 decode calls)
- Hex encoded strings being decoded at runtime
- Minified or single-character variable names in new scripts
- `eval()` on any dynamic string

---

## Medium Priority — Flag with Context

### New External Dependencies
- New `import` or `require` statements for packages not previously used
- New entries in package.json or requirements.txt

### Scope Expansion
- Skill now reads files from the user's project it didn't before
- New instructions to access browser history, cookies, or local storage
- New instructions to read other skills' files

### Behavioral Changes That Expand Permissions
- New instructions telling Claude to run commands without asking
- Removal of confirmation steps that previously existed
- New auto-apply or auto-execute behaviors

---

## Low Priority — Note but Don't Block

### Informational
- New external documentation links (GitHub, docs sites)
- References to well-known public APIs (GitHub API, npm registry)
- New comments or documentation only

---

## Context-Aware Judgment

Not every flag is a blocker. Use judgment:

- A motion design skill adding a new URL to a well-known animation library docs page = low concern
- Any skill adding `curl` to send data to an unknown endpoint = high concern
- A skill adding `git` commands = expected, low concern
- A skill adding `rm -rf` = always flag regardless of context

When in doubt, flag it and let the user decide.
