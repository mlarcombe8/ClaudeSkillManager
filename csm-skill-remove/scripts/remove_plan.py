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


def find_project_root(start=None):
    """Walk up from cwd to the nearest dir with `.claude/skills/`, or None."""
    home = Path.home().resolve()
    try:
        p = Path(start).resolve() if start else Path.cwd().resolve()
    except OSError:
        return None
    while True:
        if p == home:
            return None
        if (p / ".claude" / "skills").is_dir():
            return str(p)
        parent = p.parent
        if parent == p:
            return None
        p = parent


def _resolution_for(link_path, scope, project_root):
    if not (link_path.exists() or link_path.is_symlink()):
        return None
    return {
        "scope": scope,
        "project_root": project_root,
        "link_path": str(link_path),
        "real_path": os.path.realpath(str(link_path)),
        "link_ok": link_path.exists(),
        "is_symlink": link_path.is_symlink(),
    }


def resolve_skill_scopes(name, project_root):
    """Return every scope (user/project) where the named skill is installed."""
    found = []
    r = _resolution_for(CLAUDE_SKILLS / name, "user", None)
    if r:
        found.append(r)
    if project_root:
        r = _resolution_for(Path(project_root) / ".claude" / "skills" / name,
                            "project", project_root)
        if r:
            found.append(r)
    return found


def sibling_skills(repo_root, this_name, this_scope, project_root):
    """Other installed skills (across BOTH scopes) backed by the same repo.

    Returns a list of {"install_name", "scope"} entries. The skill being
    queried (this_name + this_scope) is excluded; siblings at the *other*
    scope with the same name are still real siblings (a separate symlink)
    and are reported.
    """
    sibs = []
    locations = [(CLAUDE_SKILLS, "user")]
    if project_root:
        locations.append((Path(project_root) / ".claude" / "skills", "project"))
    for base, scope in locations:
        if not base.is_dir():
            continue
        for item in sorted(base.iterdir()):
            if item.name == this_name and scope == this_scope:
                continue
            try:
                real = os.path.realpath(str(item))
            except OSError:
                continue
            if not Path(real).exists():
                continue
            root = git_toplevel(real)
            if root and root == repo_root:
                sibs.append({"install_name": item.name, "scope": scope})
    return sibs


def main():
    ap = argparse.ArgumentParser(
        description="Build a removal plan for an installed skill (read-only).")
    ap.add_argument("skill", help="The installed skill name (as in ~/.claude/skills "
                                 "or the current project's .claude/skills).")
    ap.add_argument("--scope", choices=("user", "project"), default=None,
                    help="Disambiguate when a skill is installed at both scopes.")
    args = ap.parse_args()
    name = args.skill

    project_root = find_project_root()

    out = {
        "skill": name,
        "project_root": project_root,
        "scope": None,
        "alternative_scopes": [],
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

    locations = resolve_skill_scopes(name, project_root)
    if not locations:
        out["status"] = "not-installed"
        out["error"] = ("No skill named '%s' under ~/.claude/skills (or the "
                        "current project's .claude/skills, if any). Run "
                        "/csm-skill-audit --list to see what's installed." % name)
        print(json.dumps(out, indent=2))
        return

    # Pick which symlink to remove. If --scope was given, honor it.
    # Otherwise: if found in only one scope, use it; if both, ask the caller
    # to disambiguate via a multi-scope status.
    chosen = None
    if args.scope:
        for loc in locations:
            if loc["scope"] == args.scope:
                chosen = loc
                break
        if chosen is None:
            out["status"] = "not-installed"
            out["error"] = ("'%s' is not installed at the requested scope (%s). "
                            "Available scopes: %s." %
                            (name, args.scope,
                             ", ".join(l["scope"] for l in locations)))
            print(json.dumps(out, indent=2))
            return
    elif len(locations) > 1:
        out["status"] = "multiple-scopes"
        out["alternative_scopes"] = [l["scope"] for l in locations]
        out["error"] = ("'%s' is installed at multiple scopes (%s); rerun with "
                        "--scope <user|project> to choose which to remove." %
                        (name, ", ".join(out["alternative_scopes"])))
        print(json.dumps(out, indent=2))
        return
    else:
        chosen = locations[0]

    out["scope"] = chosen["scope"]
    out["found"] = True
    out["link_path"] = chosen["link_path"]
    out["real_path"] = chosen["real_path"]
    out["is_symlink"] = chosen["is_symlink"]
    out["link_ok"] = chosen["link_ok"]

    if not chosen["link_ok"]:
        out["status"] = "broken-symlink"
        out["error"] = ("%s is a broken symlink (target %s is missing); only the "
                        "symlink itself needs removing." %
                        (chosen["link_path"], chosen["real_path"]))
        out["removal_plan"] = {
            "symlink_to_remove": chosen["link_path"],
            "clone_to_remove": None,
            "bundle_symlinks_to_remove": [],
            "reason_to_keep_clone": "target missing; nothing else to clean up",
            "needs_backup": False,
        }
        print(json.dumps(out, indent=2))
        return

    # Git status of the backing dir.
    root = git_toplevel(chosen["real_path"])
    if root is not None:
        out["is_git"] = True
        out["repo_root"] = root
        try:
            out["subpath"] = os.path.relpath(chosen["real_path"], root) or "."
        except ValueError:
            out["subpath"] = "?"
        remote, _, _ = run("git remote get-url origin", cwd=root)
        out["has_remote"] = bool(remote)
        out["remote"] = remote or None
        out["is_suite_skill"] = bool(remote) and "ClaudeSkillManager" in remote
        kb = du_kb(root)
        out["clone_size_kb"] = kb
        out["clone_size"] = human_size(kb)

    sibs = sibling_skills(root, name, chosen["scope"], project_root) if root else []
    out["sibling_skills"] = sibs
    out["is_multi_skill"] = len(sibs) > 0

    # Build the removal plan. `bundle_symlinks_to_remove` is now [{name, scope}]
    # so the SKILL.md can compute the correct symlink path for each member.
    plan = {
        "symlink_to_remove": chosen["link_path"],
        "scope": chosen["scope"],
        "clone_to_remove": None,
        "bundle_symlinks_to_remove": [],
        "reason_to_keep_clone": None,
        "needs_backup": False,
    }

    if root is None:
        plan["clone_to_remove"] = None
        plan["reason_to_keep_clone"] = ("not backed by a git clone; only the "
                                        "link/dir at %s will be removed" % chosen["link_path"])
        plan["needs_backup"] = False
    elif sibs:
        plan["clone_to_remove"] = None
        plan["bundle_symlinks_to_remove"] = sibs
        sib_desc = ", ".join("%s (%s)" % (s["install_name"], s["scope"]) for s in sibs)
        plan["reason_to_keep_clone"] = ("backs %d other installed skill(s): %s. "
                                        "Removing the clone would orphan them." %
                                        (len(sibs), sib_desc))
        plan["needs_backup"] = True
    else:
        plan["clone_to_remove"] = root
        plan["reason_to_keep_clone"] = None
        plan["needs_backup"] = True

    out["removal_plan"] = plan
    out["status"] = "ok"
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
