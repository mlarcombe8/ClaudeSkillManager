#!/usr/bin/env python3
"""
remove_plan.py — build a removal plan for one installed skill.

Part of csm-skill-remove (ClaudeSkillManager suite). READ-ONLY: it resolves a
named skill, identifies the backing clone and any sibling skills that share it,
flags suite skills, and emits a JSON plan describing what *would* be removed.
It never deletes, unlinks, moves, or modifies anything — csm-skill-remove's
SKILL.md drives the actual removal (backup, rm symlink, rm clone).

Mirrors the helper style of csm-skill-update/scripts/discover.py and
csm-skill-audit/scripts/audit.py.

Usage:
  python3 remove_plan.py <skill-name>

Outputs JSON: the skill, its link/clone, sibling skills sharing the clone,
whether the clone is safe to delete, suite-skill flag, and a `removal_plan`
block the SKILL.md uses to drive the operation. `status` flags edge cases.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

CLAUDE_SKILLS = Path.home() / ".claude" / "skills"
AGENTS_SKILLS = Path.home() / ".agents" / "skills"


def run(cmd, cwd=None):
    """Run a shell command and return (stdout, stderr, returncode)."""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except OSError as exc:
        return "", str(exc), 1


def git_toplevel(path):
    """Return the git repo root for a path, or None if not in a git repo."""
    out, _, rc = run("git rev-parse --show-toplevel", cwd=path)
    return out if rc == 0 and out else None


def du_kb(path):
    out, _, rc = run('du -sk "%s"' % path)
    if rc != 0 or not out:
        return None
    try:
        return int(out.split()[0])
    except (ValueError, IndexError):
        return None


def human_size(kb):
    if kb is None:
        return "unknown"
    size = float(kb) * 1024.0
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0 or unit == "GB":
            return "%d %s" % (int(size), unit) if unit == "B" else "%.1f %s" % (size, unit)
        size /= 1024.0
    return "%.1f GB" % size


def resolve_skill(name):
    """Look up ~/.claude/skills/<name>; None if not present."""
    link = CLAUDE_SKILLS / name
    if not (link.exists() or link.is_symlink()):
        return None
    return {
        "link_path": str(link),
        "real_path": os.path.realpath(str(link)),
        "link_ok": link.exists(),
        "is_symlink": link.is_symlink(),
    }


def sibling_skills(repo_root, this_name):
    """Other installed skills whose real path is inside the same repo."""
    sibs = []
    if not CLAUDE_SKILLS.exists():
        return sibs
    for item in sorted(CLAUDE_SKILLS.iterdir()):
        if item.name == this_name:
            continue
        try:
            real = os.path.realpath(str(item))
        except OSError:
            continue
        if not Path(real).exists():
            continue
        root = git_toplevel(real)
        if root and root == repo_root:
            sibs.append(item.name)
    return sibs


def main():
    ap = argparse.ArgumentParser(
        description="Build a removal plan for an installed skill (read-only).")
    ap.add_argument("skill", help="The installed skill name (as in ~/.claude/skills).")
    args = ap.parse_args()
    name = args.skill

    out = {
        "skill": name,
        "found": False,
        "link_path": None,
        "real_path": None,
        "is_symlink": False,
        "link_ok": False,
        "is_git": False,
        "repo_root": None,
        "subpath": None,
        "has_remote": False,
        "remote": None,
        "clone_size": None,
        "clone_size_kb": None,
        "sibling_skills": [],
        "is_multi_skill": False,
        "is_suite_skill": False,
        "status": None,
        "error": None,
        "removal_plan": None,
    }

    info = resolve_skill(name)
    if info is None:
        out["status"] = "not-installed"
        out["error"] = ("No skill named '%s' under ~/.claude/skills. Run "
                        "/csm-skill-audit --list to see what's installed." % name)
        print(json.dumps(out, indent=2))
        return

    out["found"] = True
    out["link_path"] = info["link_path"]
    out["real_path"] = info["real_path"]
    out["is_symlink"] = info["is_symlink"]
    out["link_ok"] = info["link_ok"]

    if not info["link_ok"]:
        # Dangling symlink — still trivially removable (just rm the link).
        out["status"] = "broken-symlink"
        out["error"] = ("~/.claude/skills/%s is a broken symlink (target %s is "
                        "missing); only the symlink itself needs removing." % (name, info["real_path"]))
        out["removal_plan"] = {
            "symlink_to_remove": info["link_path"],
            "clone_to_remove": None,
            "bundle_symlinks_to_remove": [],
            "reason_to_keep_clone": "target missing; nothing else to clean up",
            "needs_backup": False,
        }
        print(json.dumps(out, indent=2))
        return

    # Git status of the backing dir.
    root = git_toplevel(info["real_path"])
    if root is not None:
        out["is_git"] = True
        out["repo_root"] = root
        try:
            out["subpath"] = os.path.relpath(info["real_path"], root) or "."
        except ValueError:
            out["subpath"] = "?"
        remote, _, _ = run("git remote get-url origin", cwd=root)
        out["has_remote"] = bool(remote)
        out["remote"] = remote or None
        out["is_suite_skill"] = bool(remote) and "ClaudeSkillManager" in remote
        kb = du_kb(root)
        out["clone_size_kb"] = kb
        out["clone_size"] = human_size(kb)

    sibs = sibling_skills(root, name) if root else []
    out["sibling_skills"] = sibs
    out["is_multi_skill"] = len(sibs) > 0

    # Build the removal plan.
    plan = {
        "symlink_to_remove": info["link_path"],
        "clone_to_remove": None,
        "bundle_symlinks_to_remove": [],
        "reason_to_keep_clone": None,
        "needs_backup": False,
    }

    if root is None:
        # Not git-managed: the "real path" *is* the skill content (a directly
        # installed dir, or just a stray symlink target outside any git repo).
        # Remove the symlink/dir but leave anything outside the skill's own
        # footprint alone.
        plan["clone_to_remove"] = None
        plan["reason_to_keep_clone"] = ("not backed by a git clone; only the "
                                        "link/dir at ~/.claude/skills/%s will be removed" % name)
        plan["needs_backup"] = False
    elif sibs:
        # Multi-skill clone — never delete it just because one symlink is going.
        # The SKILL.md offers "remove just this symlink" vs "remove the whole bundle".
        plan["clone_to_remove"] = None
        plan["bundle_symlinks_to_remove"] = sibs  # only used if user chooses "whole bundle"
        plan["reason_to_keep_clone"] = ("backs %d other installed skill(s): %s. "
                                        "Removing the clone would orphan them." %
                                        (len(sibs), ", ".join(sibs)))
        plan["needs_backup"] = True   # bundle removal touches multiple skills
    else:
        # Single-skill clone — safe to delete the whole clone after the symlink.
        plan["clone_to_remove"] = root
        plan["reason_to_keep_clone"] = None
        plan["needs_backup"] = True

    out["removal_plan"] = plan
    out["status"] = "ok"
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
