#!/usr/bin/env python3
"""
Skill Update Discovery Script

Scans installed skills under ~/.claude/skills and ~/.agents/skills, resolves each
to its real location, finds the enclosing git repo root, and GROUPS skills by repo.

This is multi-skill-repo aware: when one git repo backs several installed skills
(a bundle/monorepo), they are reported together under that repo, because a single
`git pull` updates all of them at once. Skills with no git root are reported
separately as "cannot be auto-updated".

Outputs JSON:
{
  "summary": {...},
  "repos": [
     {
       "repo_path", "remote", "is_git", "is_multi_skill",
       "current_branch", "last_updated", "commits_behind", "has_updates",
       "error",
       "skills": [ {"install_name", "declared_name", "subpath", "link_path"} , ... ]
     }, ...
  ],
  "non_git_skills": [ {"install_name", "declared_name", "path", "link_path"} , ... ]
}
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SKILL_DIRS = [Path.home() / ".claude" / "skills", Path.home() / ".agents" / "skills"]


def run(cmd, cwd=None):
    """Run a shell command and return (stdout, stderr, returncode)."""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def git_toplevel(path):
    """Return the git repo root for a path, or None if not in a git repo."""
    out, _, rc = run("git rev-parse --show-toplevel", cwd=str(path))
    if rc != 0 or not out:
        return None
    return Path(out)


def read_declared_name(skill_md):
    """Read the `name:` field from a SKILL.md frontmatter, if present."""
    try:
        with open(skill_md, "r", encoding="utf-8", errors="ignore") as f:
            in_fm = False
            for line in f:
                s = line.strip()
                if s == "---":
                    if not in_fm:
                        in_fm = True
                        continue
                    break  # end of frontmatter
                if in_fm and s.lower().startswith("name:"):
                    return s.split(":", 1)[1].strip().strip("\"'")
    except OSError:
        return None
    return None


def collect_installed():
    """Collect installed skill entries from both skill dirs, deduped by real path.

    Returns a list of dicts: {install_name, link_path, real_path, skill_md, declared_name}.
    Only entries whose resolved directory contains a SKILL.md count as installed skills,
    so bare repo roots (e.g. a bundle root with no top-level SKILL.md) are skipped here
    and instead surface via their member skills' symlinks.
    """
    entries = {}
    for base in SKILL_DIRS:
        if not base.exists():
            continue
        for item in sorted(base.iterdir()):
            try:
                real = item.resolve()
            except OSError:
                continue  # broken symlink
            skill_md = real / "SKILL.md"
            if not skill_md.is_file():
                continue
            key = str(real)
            if key in entries:
                continue  # same physical skill reached via two dirs
            entries[key] = {
                "install_name": item.name,
                "link_path": str(item),
                "real_path": str(real),
                "skill_md": str(skill_md),
                "declared_name": read_declared_name(skill_md),
            }
    return list(entries.values())


def rel_subpath(real_path, root):
    try:
        return os.path.relpath(real_path, str(root)) or "."
    except ValueError:
        return "?"


def main():
    installed = collect_installed()
    if not installed:
        print(json.dumps({
            "summary": {"installed_skills": 0, "git_repos": 0, "git_skills": 0,
                        "multi_skill_repos": 0, "repos_with_updates": 0,
                        "non_git_skills": 0, "scanned_at": datetime.now().isoformat()},
            "repos": [], "non_git_skills": [],
        }, indent=2))
        return

    repos = {}        # repo_root str -> repo info
    non_git = []      # skills with no git root

    for e in installed:
        root = git_toplevel(e["real_path"])
        if root is None:
            non_git.append({
                "install_name": e["install_name"],
                "declared_name": e["declared_name"],
                "path": e["real_path"],
                "link_path": e["link_path"],
                "is_git": False,
                "error": "not a git repository",
            })
            continue
        rk = str(root)
        repos.setdefault(rk, {
            "repo_path": rk,
            "remote": None,
            "is_git": True,
            "is_multi_skill": False,
            "current_branch": None,
            "last_updated": None,
            "commits_behind": 0,
            "has_updates": False,
            "error": None,
            "skills": [],
        })
        repos[rk]["skills"].append({
            "install_name": e["install_name"],
            "declared_name": e["declared_name"],
            "subpath": rel_subpath(e["real_path"], root),
            "link_path": e["link_path"],
        })

    # Enrich each repo with git status + a fetch (errors are surfaced, never hidden).
    for rk, info in repos.items():
        info["is_multi_skill"] = len(info["skills"]) > 1
        info["skills"].sort(key=lambda s: s["install_name"])

        remote, _, _ = run("git remote get-url origin", cwd=rk)
        info["remote"] = remote or None

        branch, _, _ = run("git rev-parse --abbrev-ref HEAD", cwd=rk)
        info["current_branch"] = branch or "main"

        last_date, _, _ = run("git log -1 --format=%ci", cwd=rk)
        info["last_updated"] = last_date or None

        # Fetch the tracked branch; fall back to a bare fetch.
        _, ferr1, frc1 = run(f"git fetch origin {info['current_branch']}", cwd=rk)
        if frc1 != 0:
            _, ferr2, frc2 = run("git fetch origin", cwd=rk)
            if frc2 != 0:
                info["error"] = "fetch failed: " + ((ferr1 or ferr2)[:160])

        if info["error"] is None:
            behind, _, _ = run("git rev-list HEAD..FETCH_HEAD --count", cwd=rk)
            try:
                info["commits_behind"] = int(behind)
            except (ValueError, TypeError):
                info["commits_behind"] = 0
            info["has_updates"] = info["commits_behind"] > 0

    repo_list = sorted(repos.values(), key=lambda r: r["repo_path"])
    non_git_sorted = sorted(non_git, key=lambda s: s["install_name"])

    git_skills = sum(len(r["skills"]) for r in repo_list)
    output = {
        "summary": {
            "installed_skills": git_skills + len(non_git_sorted),
            "git_repos": len(repo_list),
            "git_skills": git_skills,
            "multi_skill_repos": sum(1 for r in repo_list if r["is_multi_skill"]),
            "repos_with_updates": sum(1 for r in repo_list if r["has_updates"]),
            "non_git_skills": len(non_git_sorted),
            "scanned_at": datetime.now().isoformat(),
        },
        "repos": repo_list,
        "non_git_skills": non_git_sorted,
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
