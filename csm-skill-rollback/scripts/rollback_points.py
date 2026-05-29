#!/usr/bin/env python3
"""
rollback_points.py — list rollback targets for one installed skill.

Part of csm-skill-rollback (ClaudeSkillManager suite). READ-ONLY: it resolves a
skill to its backing git repo and lists the local commit history (candidate
rollback points) plus the context the SKILL.md needs to decide what to do. It
never checks out, resets, fetches, or modifies anything — csm-skill-rollback's
SKILL.md drives the diff, security check, and the actual rollback.

Rollback targets come from *local* history (clones already contain past
versions), so listing works offline. Mirrors the helper style of
csm-skill-update/scripts/discover.py and csm-skill-audit/scripts/audit.py.

Usage:
  python3 rollback_points.py <skill-name> [--limit N]

Outputs JSON: the skill, its repo + subpath, current commit, sibling skills
that share the repo (rolling back the repo affects them too), and the candidate
rollback points (older commits). `status` flags the edge cases.
"""

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

CLAUDE_SKILLS = Path.home() / ".claude" / "skills"


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
    user_link = CLAUDE_SKILLS / name
    r = _resolution_for(user_link, "user", None)
    if r:
        found.append(r)
    if project_root:
        proj_link = Path(project_root) / ".claude" / "skills" / name
        r = _resolution_for(proj_link, "project", project_root)
        if r:
            found.append(r)
    return found


def sibling_skills(repo_root, this_name, project_root):
    """Other installed skills (across BOTH scopes) backed by the same repo."""
    sibs = []
    seen = set()
    locations = [(CLAUDE_SKILLS, "user")]
    if project_root:
        locations.append((Path(project_root) / ".claude" / "skills", "project"))
    for base, scope in locations:
        if not base.is_dir():
            continue
        for item in sorted(base.iterdir()):
            if item.name == this_name and scope == "user":
                continue
            if item.name == this_name and scope == "project":
                continue
            try:
                real = os.path.realpath(str(item))
            except OSError:
                continue
            if not Path(real).exists():
                continue
            root = git_toplevel(real)
            if root and root == repo_root:
                key = (item.name, scope)
                if key in seen:
                    continue
                seen.add(key)
                sibs.append({"install_name": item.name, "scope": scope})
    return sibs


def main():
    ap = argparse.ArgumentParser(
        description="List rollback points for an installed skill (read-only).")
    ap.add_argument("skill", help="The installed skill name (as in ~/.claude/skills "
                                 "or the current project's .claude/skills).")
    ap.add_argument("--scope", choices=("user", "project"), default=None,
                    help="Disambiguate when a skill is installed at both scopes.")
    ap.add_argument("--limit", type=int, default=25,
                    help="Max number of rollback points to list (default 25).")
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
        "link_ok": False,
        "real_path": None,
        "skillmd_present": False,
        "is_git": False,
        "repo_root": None,
        "subpath": None,
        "has_remote": False,
        "remote": None,
        "branch": None,
        "current_commit": None,
        "is_multi_skill": False,
        "sibling_skills": [],
        "points": [],
        "points_scope": None,
        "status": None,
        "error": None,
    }

    locations = resolve_skill_scopes(name, project_root)
    if not locations:
        out["status"] = "not-installed"
        out["error"] = ("No skill named '%s' under ~/.claude/skills (or the "
                        "current project's .claude/skills, if any). Run "
                        "/csm-skill-audit --list to see what's installed." % name)
        print(json.dumps(out, indent=2))
        return

    # Pick which scope to roll back. If the caller passed --scope, honor it
    # (and error if not found there). Otherwise pick the unique location, or
    # fall through with a multi-scope status if both exist.
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
                        "--scope <user|project> to choose." %
                        (name, ", ".join(out["alternative_scopes"])))
        print(json.dumps(out, indent=2))
        return
    else:
        chosen = locations[0]

    out["scope"] = chosen["scope"]
    out["found"] = True
    out["link_path"] = chosen["link_path"]
    out["real_path"] = chosen["real_path"]
    out["link_ok"] = chosen["link_ok"]

    if not chosen["link_ok"]:
        out["status"] = "broken-symlink"
        out["error"] = ("%s points to a missing target (%s). Reinstall via "
                        "/csm-skill-install." % (chosen["link_path"], chosen["real_path"]))
        print(json.dumps(out, indent=2))
        return

    out["skillmd_present"] = (Path(chosen["real_path"]) / "SKILL.md").is_file()

    root = git_toplevel(chosen["real_path"])
    if root is None:
        out["status"] = "not-git"
        out["error"] = ("'%s' is not backed by a git repo, so it has no version "
                        "history to roll back to. Reinstall it via /csm-skill-install "
                        "to make it git-managed." % name)
        print(json.dumps(out, indent=2))
        return
    out["is_git"] = True
    out["repo_root"] = root

    try:
        subpath = os.path.relpath(chosen["real_path"], root) or "."
    except ValueError:
        subpath = "?"
    out["subpath"] = subpath

    remote, _, _ = run("git remote get-url origin", cwd=root)
    out["has_remote"] = bool(remote)
    out["remote"] = remote or None
    branch, _, _ = run("git rev-parse --abbrev-ref HEAD", cwd=root)
    out["branch"] = branch or "HEAD"

    head, _, rc = run("git rev-parse HEAD", cwd=root)
    if rc == 0 and head:
        csub, _, _ = run("git log -1 --format=%s", cwd=root)
        cdate, _, _ = run("git log -1 --format=%cI", cwd=root)
        out["current_commit"] = {"sha": head, "short": head[:9],
                                 "date": cdate or None, "subject": csub or ""}

    sibs = sibling_skills(root, name, project_root)
    out["sibling_skills"] = sibs
    out["is_multi_skill"] = len(sibs) > 0

    # Candidate rollback points: commits touching this skill's subpath (so the
    # list reflects versions of *this* skill). Each is a whole-repo commit — the
    # rollback resets the repo to it, which is why multi-skill repos warn.
    scope = subpath if subpath not in (".", "?") else ""
    fmt = "%H%x1f%cI%x1f%an%x1f%s"
    cmd = "git log -n %d --format=%s" % (args.limit, shlex.quote(fmt))
    if scope:
        cmd += " -- %s" % shlex.quote(scope)
    log_out, _, rc = run(cmd, cwd=root)
    head_sha = out["current_commit"]["sha"] if out["current_commit"] else None
    points = []
    if rc == 0 and log_out:
        for line in log_out.split("\n"):
            parts = line.split("\x1f")
            if len(parts) < 4:
                continue
            sha, date, author, subject = parts[0], parts[1], parts[2], parts[3]
            points.append({
                "sha": sha, "short": sha[:9], "date": date,
                "author": author, "subject": subject,
                "is_current": bool(head_sha) and sha == head_sha,
            })
    out["points"] = points
    out["points_scope"] = "subpath" if scope else "repo"

    earlier = [p for p in points if not p["is_current"]]
    if not points:
        out["status"] = "no-history"
        out["error"] = "No commit history found for this skill."
    elif not earlier:
        out["status"] = "no-history"
        out["error"] = "Only one version exists; there's nothing earlier to roll back to."
    else:
        out["status"] = "ok"

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
