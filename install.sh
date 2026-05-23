#!/bin/sh
# ClaudeSkillManager installer
#
# Installs the ClaudeSkillManager suite the "proper" way: clones the repo so it
# keeps a live git remote, then symlinks its four skills into ~/.claude/skills.
# Because the install stays git-connected, the skills can be updated, rolled
# back, and audited later (unlike a plain copy or `npx skills add`).
#
# POSIX sh only — no bashisms. Safe to run via:
#   curl -fsSL https://raw.githubusercontent.com/mlarcombe8/ClaudeSkillManager/main/install.sh | sh
# or after cloning:  sh install.sh

REPO_URL="https://github.com/mlarcombe8/ClaudeSkillManager.git"
SUITE_DIR="$HOME/.agents/skills/ClaudeSkillManager"
SKILLS_DIR="$HOME/.claude/skills"
SKILLS="csm-skill-install csm-skill-update csm-skill-finder csm-skill-audit"

# --------------------------------------------------------------------------- #
# Output helpers
# --------------------------------------------------------------------------- #
info() { printf '%s\n' "$*"; }
note() { printf '   - %s\n' "$*"; }
errln() { printf 'ERROR: %s\n' "$*" >&2; }

fail() {
    errln "$1"
    {
        printf '\n'
        printf 'Installation failed.\n'
        printf 'You can:\n'
        printf '  1. Fix the issue above and re-run this script.\n'
        printf '  2. Install manually — see the "Manual install" section of the README:\n'
        printf '     https://github.com/mlarcombe8/ClaudeSkillManager#manual-install\n'
    } >&2
    exit 1
}

# Yes/No prompt that still works when the script is piped to `sh` (reads the
# real terminal via /dev/tty). $1 = question, $2 = default ("y"/"n") used only
# when NO usable terminal exists (e.g. a non-interactive/automated run).
# An interactive empty answer (just Enter) counts as "no", matching the [y/N].
confirm() {
    question="$1"
    ni_default="$2"
    answer=""
    have_tty=0
    # Probe whether /dev/tty can actually be opened (not just its mode bits);
    # the brace group keeps any "Device not configured" error off the screen.
    if { true < /dev/tty; } 2> /dev/null; then
        have_tty=1
        printf '%s [y/N] ' "$question" > /dev/tty 2> /dev/null
        { read answer < /dev/tty; } 2> /dev/null || {
            answer=""
            have_tty=0
        }
    fi
    if [ "$have_tty" -eq 0 ]; then
        info "$question (no terminal; using default \"$ni_default\")"
        answer="$ni_default"
    fi
    case "$answer" in
        [yY] | [yY][eE][sS]) return 0 ;;
        *) return 1 ;;
    esac
}

# --------------------------------------------------------------------------- #
# Install
# --------------------------------------------------------------------------- #
info "==> ClaudeSkillManager installer"

# 1. Require git.
if ! command -v git > /dev/null 2>&1; then
    fail "git is not installed or not on PATH. Install git and re-run. (macOS: 'xcode-select --install' or 'brew install git'; Debian/Ubuntu: 'sudo apt-get install git'.)"
fi

# 2. Handle an existing clone.
skip_clone=0
if [ -e "$SUITE_DIR" ]; then
    info "==> A copy already exists at: $SUITE_DIR"
    if confirm "    Reuse it and (re)link the skills?" "y"; then
        info "    Reusing existing directory (skipping git clone)."
        skip_clone=1
    else
        info "Aborted at your request. Nothing was changed."
        exit 0
    fi
fi

# 3. Clone (unless reusing an existing copy).
if [ "$skip_clone" -eq 0 ]; then
    info "==> Cloning $REPO_URL"
    if ! mkdir -p "$HOME/.agents/skills"; then
        fail "Could not create $HOME/.agents/skills"
    fi
    if ! git clone "$REPO_URL" "$SUITE_DIR"; then
        fail "git clone failed. Check your internet connection and that the repo URL is reachable."
    fi
fi

# Sanity-check the clone actually contains the four skills.
for name in $SKILLS; do
    if [ ! -f "$SUITE_DIR/$name/SKILL.md" ]; then
        fail "Expected skill is missing after clone: $SUITE_DIR/$name/SKILL.md"
    fi
done

# 4. Ensure ~/.claude/skills exists.
if ! mkdir -p "$SKILLS_DIR"; then
    fail "Could not create $SKILLS_DIR"
fi

# 5 & 6. Create symlinks, skipping any that already exist.
info "==> Linking skills into $SKILLS_DIR"
created=0
skipped=0
for name in $SKILLS; do
    target="$SUITE_DIR/$name"
    link="$SKILLS_DIR/$name"
    if [ -e "$link" ] || [ -L "$link" ]; then
        note "$name: already exists — skipping"
        skipped=$((skipped + 1))
        continue
    fi
    if ln -s "$target" "$link"; then
        note "$name: linked"
        created=$((created + 1))
    else
        fail "Failed to create symlink: $link -> $target"
    fi
done

# 7. Verify every symlink resolves to a readable SKILL.md.
info "==> Verifying"
failures=0
for name in $SKILLS; do
    if [ -f "$SKILLS_DIR/$name/SKILL.md" ]; then
        note "$name: OK"
    else
        note "$name: NOT RESOLVING"
        failures=$((failures + 1))
    fi
done
if [ "$failures" -ne 0 ]; then
    fail "$failures skill link(s) did not resolve (see notes above)."
fi

# 8. Success.
info ""
info "============================================================"
info " ClaudeSkillManager installed successfully"
info "============================================================"
info " Repo:     $SUITE_DIR"
info " Skills:   $SKILLS_DIR/{csm-skill-install,csm-skill-update,csm-skill-finder,csm-skill-audit}"
info " Linked:   $created    Already present: $skipped"
info ""
info " The suite provides four skills:"
info "   /csm-skill-install  - install skills properly (git clone + remote)"
info "   /csm-skill-update   - review and apply updates to installed skills"
info "   /csm-skill-finder   - discover skills from the open ecosystem"
info "   /csm-skill-audit    - audit your skill library's health"
info ""
info " >> Start a NEW Claude Code session so the skills load. <<"
info "    Then try:  /csm-skill-audit"
info "============================================================"

exit 0
