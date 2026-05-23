#!/usr/bin/env python3
"""
csm-skill-audit data-gathering script for the ClaudeSkillManager suite.

Scans installed Claude Code skills and emits a single JSON document describing
the health of the skill library. It is READ-ONLY: it never installs, updates,
moves, deletes, or otherwise modifies anything. Interpretation, presentation,
and any fixes are left to Claude (see SKILL.md), which only ever hands off to
/csm-skill-install or /csm-skill-update — it does not fix things itself.

Severity model
--------------
  critical  broken symlink, missing SKILL.md
  warning   no git remote, behind on updates, drift vs upstream-baseline.md,
            installed without git (npx skills add / manual copy)
  info      orphaned files, orphaned clones, storage footprint, suite version

Health score
------------
  Starts at 100, minus SCORE_CRITICAL per critical finding and SCORE_WARNING
  per warning finding (info costs nothing), clamped to [0, 100], then mapped to
  a letter grade. The rubric is duplicated in SKILL.md so Claude can explain it.

Usage
-----
  python3 audit.py            # full audit (fetches remotes to check "behind")
  python3 audit.py --no-fetch # skip network fetches; "behind" becomes unknown

Output: pretty-printed JSON on stdout. Non-fatal problems are collected under
the top-level "errors" array rather than crashing the run.
"""

import argparse
import difflib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

CLAUDE_SKILLS = Path.home() / ".claude" / "skills"
AGENTS_SKILLS = Path.home() / ".agents" / "skills"
SCAN_ROOTS = [CLAUDE_SKILLS, AGENTS_SKILLS]

# Health scoring (kept in sync with SKILL.md).
SCORE_CRITICAL = 25
SCORE_WARNING = 8
SCORE_INFO = 0

SCHEMA_VERSION = 1


# --------------------------------------------------------------------------- #
# Small helpers (mirrors the style of csm-skill-update/scripts/discover.py)
# --------------------------------------------------------------------------- #
def run(cmd, cwd=None, timeout=None):
    """Run a shell command and return (stdout, stderr, returncode)."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, cwd=cwd, timeout=timeout
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", "timeout", 124


def git_toplevel(path):
    """Return the git repo root for a path, or None if not in a git repo."""
    out, _, rc = run("git rev-parse --show-toplevel", cwd=str(path))
    if rc != 0 or not out:
        return None
    return out


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


def du_kb(path):
    """Disk usage of a path in kilobytes (best-effort, via `du -sk`)."""
    out, _, rc = run('du -sk "%s"' % path)
    if rc != 0 or not out:
        return None
    try:
        return int(out.split()[0])
    except (ValueError, IndexError):
        return None


def human_size(kb):
    """Render a kilobyte count as a human-readable string."""
    if kb is None:
        return "unknown"
    size = float(kb) * 1024.0
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            return "%.1f %s" % (size, unit) if unit != "B" else "%d B" % int(size)
        size /= 1024.0
    return "%.1f TB" % size


def changed_line_count(a_text, b_text):
    """Count added/removed lines between two texts (a unified-diff delta)."""
    diff = difflib.unified_diff(
        a_text.splitlines(), b_text.splitlines(), lineterm=""
    )
    n = 0
    for line in diff:
        if line.startswith("+") and not line.startswith("+++"):
            n += 1
        elif line.startswith("-") and not line.startswith("---"):
            n += 1
    return n


def grade_for(score):
    """Map a 0-100 health score to (letter, label)."""
    if score >= 90:
        return "A", "Healthy"
    if score >= 75:
        return "B", "Good"
    if score >= 60:
        return "C", "Fair"
    if score >= 40:
        return "D", "Poor"
    return "F", "Critical"


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
def _new_skill(name, link_path, real_path, is_symlink, link_ok, skillmd_present, skill_md):
    return {
        "install_name": name,
        "declared_name": read_declared_name(skill_md) if skillmd_present else None,
        "link_path": link_path,
        "real_path": real_path,
        "is_symlink": is_symlink,
        "link_ok": link_ok,
        "skillmd_present": skillmd_present,
        # git/drift fields filled in later
        "git": None,
        "drift": None,
        "severity": "ok",
    }


def discover_active_skills(errors):
    """Enumerate the *active* installed skills under ~/.claude/skills.

    ~/.claude/skills is what Claude Code actually loads, so it is the canonical
    "installed" set. ~/.agents/skills holds the clones/sources and is used only
    for orphan detection.

    Classification matters: a *symlink* is intended as a skill, so a symlink with
    a missing target or no SKILL.md is a genuine (critical) problem. A *plain
    file or directory* sitting in ~/.claude/skills that has no SKILL.md is NOT a
    skill — it's stray/orphaned content (e.g. leftover `data/` and `scripts/`
    from an old flat install) and is reported as info, not critical.

    Returns (skills, orphaned_files, orphaned_dirs).
    """
    skills = []
    orphaned_files = []
    orphaned_dirs = []
    if not CLAUDE_SKILLS.exists():
        errors.append("scan root missing: %s" % CLAUDE_SKILLS)
        return skills, orphaned_files, orphaned_dirs

    for item in sorted(CLAUDE_SKILLS.iterdir()):
        name = item.name

        # ---- real (non-symlink) entries -------------------------------- #
        if not item.is_symlink():
            if item.is_file():
                # A loose file (e.g. a SKILL.md dropped at the root) — orphaned.
                orphaned_files.append({
                    "path": str(item), "name": name, "size": human_size(du_kb(str(item))),
                })
                continue
            if item.is_dir():
                skill_md = item / "SKILL.md"
                if skill_md.is_file():
                    # A directly-installed skill (flat / npx / manual copy).
                    skills.append(_new_skill(
                        name, str(item), str(item.resolve()),
                        is_symlink=False, link_ok=True, skillmd_present=True, skill_md=skill_md,
                    ))
                else:
                    # A non-skill directory living in the skills dir — orphaned.
                    orphaned_dirs.append({
                        "path": str(item), "name": name, "size": human_size(du_kb(str(item))),
                    })
                continue
            continue  # sockets/fifos/etc — ignore

        # ---- symlink entries (the suite's normal install shape) -------- #
        broken = not item.exists()
        real_path = os.path.realpath(str(item))
        skill_md = Path(real_path) / "SKILL.md"
        skillmd_present = (not broken) and skill_md.is_file()
        skills.append(_new_skill(
            name, str(item), real_path,
            is_symlink=True, link_ok=not broken, skillmd_present=skillmd_present, skill_md=skill_md,
        ))

    return skills, orphaned_files, orphaned_dirs


def find_orphaned_clones(skills, errors):
    """Clone dirs under ~/.agents/skills that no active skill links into."""
    orphans = []
    if not AGENTS_SKILLS.exists():
        return orphans
    referenced = [s["real_path"] for s in skills if s["link_ok"]]
    for child in sorted(AGENTS_SKILLS.iterdir()):
        if not child.is_dir():
            continue
        base = str(child.resolve())
        used = any(rp == base or rp.startswith(base + os.sep) for rp in referenced)
        if not used:
            orphans.append({
                "path": str(child),
                "name": child.name,
                "size": human_size(du_kb(str(child))),
            })
    return orphans


# --------------------------------------------------------------------------- #
# Per-repo git enrichment (cached so multi-skill repos are fetched once)
# --------------------------------------------------------------------------- #
def repo_git_status(repo_root, do_fetch):
    """Collect git status for a repo root: remote, branch, behind count."""
    remote, _, _ = run("git remote get-url origin", cwd=repo_root)
    branch, _, _ = run("git rev-parse --abbrev-ref HEAD", cwd=repo_root)
    branch = branch or "main"
    last_date, _, _ = run("git log -1 --format=%ci", cwd=repo_root)

    status = {
        "is_repo": True,
        "repo_root": repo_root,
        "has_remote": bool(remote),
        "remote": remote or None,
        "branch": branch,
        "last_commit_date": last_date or None,
        "commits_behind": 0,
        "fetch_ok": None,
        "fetch_error": None,
    }

    if not remote:
        return status  # nothing to fetch / compare against

    if not do_fetch:
        status["fetch_ok"] = False
        status["fetch_error"] = "skipped (--no-fetch)"
        status["commits_behind"] = None  # unknown
        return status

    _, ferr, frc = run("git fetch origin %s" % branch, cwd=repo_root, timeout=30)
    if frc != 0:
        _, ferr2, frc2 = run("git fetch origin", cwd=repo_root, timeout=30)
        if frc2 != 0:
            status["fetch_ok"] = False
            status["fetch_error"] = (ferr or ferr2 or "fetch failed")[:200]
            status["commits_behind"] = None  # unknown
            return status

    status["fetch_ok"] = True
    behind, _, _ = run("git rev-list HEAD..FETCH_HEAD --count", cwd=repo_root)
    try:
        status["commits_behind"] = int(behind)
    except (ValueError, TypeError):
        status["commits_behind"] = 0
    return status


def check_drift(skill):
    """If a skill ships references/upstream-baseline.md, compare it to SKILL.md."""
    real = Path(skill["real_path"])
    baseline = real / "references" / "upstream-baseline.md"
    current = real / "SKILL.md"
    if not (baseline.is_file() and current.is_file()):
        return None
    try:
        base_text = baseline.read_text(encoding="utf-8", errors="ignore")
        cur_text = current.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    n = changed_line_count(base_text, cur_text)
    return {"checked": True, "differs": n > 0, "changed_lines": n}


# --------------------------------------------------------------------------- #
# Finding helpers
# --------------------------------------------------------------------------- #
def make_finding(fid, title, detail, skills, handoff=None):
    return {
        "id": fid,
        "title": title,
        "detail": detail,
        "skills": skills,
        "handoff": handoff,
    }


def bump(skill, severity):
    """Raise a skill's severity to the highest seen."""
    order = {"ok": 0, "info": 1, "warning": 2, "critical": 3}
    if order[severity] > order[skill["severity"]]:
        skill["severity"] = severity


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(description="Audit installed Claude Code skills (read-only).")
    parser.add_argument("--no-fetch", action="store_true",
                        help="Skip network fetches; 'behind on updates' becomes unknown.")
    args = parser.parse_args()
    do_fetch = not args.no_fetch

    errors = []
    critical = []
    warning = []
    info = []

    skills, orphaned_files, orphaned_dirs = discover_active_skills(errors)

    # --- Critical: broken symlinks & missing SKILL.md ---------------------- #
    for s in skills:
        if not s["link_ok"]:
            bump(s, "critical")
            critical.append(make_finding(
                "broken_symlink",
                "Broken symlink",
                "%s -> %s (target does not exist)" % (s["link_path"], s["real_path"]),
                [s["install_name"]],
                handoff="/csm-skill-install",
            ))
        elif not s["skillmd_present"]:
            bump(s, "critical")
            critical.append(make_finding(
                "missing_skillmd",
                "Missing SKILL.md",
                "No SKILL.md found at %s" % s["real_path"],
                [s["install_name"]],
                handoff="/csm-skill-install",
            ))

    # --- Group healthy-enough skills by backing repo ----------------------- #
    repo_members = {}   # repo_root -> [skill, ...]
    repo_status = {}    # repo_root -> status dict
    non_git_skills = []

    for s in skills:
        if not s["link_ok"] or not s["skillmd_present"]:
            continue  # already critical; skip git checks
        root = git_toplevel(s["real_path"])
        if root is None:
            s["git"] = {"is_repo": False, "repo_root": None, "has_remote": False,
                        "remote": None, "branch": None, "last_commit_date": None,
                        "commits_behind": None, "fetch_ok": None, "fetch_error": None}
            non_git_skills.append(s)
        else:
            repo_members.setdefault(root, []).append(s)

    for root, members in repo_members.items():
        status = repo_status.get(root)
        if status is None:
            status = repo_git_status(root, do_fetch)
            repo_status[root] = status
        for s in members:
            s["git"] = dict(status)

    # --- Warning: installed without git (npx / manual) --------------------- #
    if non_git_skills:
        names = [s["install_name"] for s in non_git_skills]
        for s in non_git_skills:
            bump(s, "warning")
        warning.append(make_finding(
            "no_git",
            "Installed without git (npx skills add / manual copy)",
            "These skills are not backed by a git repo, so they can't be updated, "
            "diffed, rolled back, or audited for changes. Reinstall via /csm-skill-install "
            "to give them a git connection.",
            names,
            handoff="/csm-skill-install",
        ))

    # --- Warning: no git remote / behind on updates (per repo) ------------- #
    for root, status in sorted(repo_status.items()):
        members = repo_members[root]
        names = [s["install_name"] for s in members]
        repo_name = os.path.basename(root)

        if not status["has_remote"]:
            for s in members:
                bump(s, "warning")
            warning.append(make_finding(
                "no_remote",
                "No git remote",
                "Repo '%s' is a git repo but has no 'origin' remote, so updates "
                "can't be fetched. Reinstall via /csm-skill-install to reconnect it." % repo_name,
                names,
                handoff="/csm-skill-install",
            ))
            continue

        behind = status["commits_behind"]
        if behind is None:
            errors.append("could not determine update status for '%s': %s"
                          % (repo_name, status["fetch_error"] or "unknown"))
        elif behind > 0:
            for s in members:
                bump(s, "warning")
            warning.append(make_finding(
                "behind",
                "Behind on updates",
                "Repo '%s' is %d commit(s) behind origin/%s. Review and apply via "
                "/csm-skill-update.%s" % (
                    repo_name, behind, status["branch"],
                    " Updating pulls all of: %s." % ", ".join(names) if len(names) > 1 else "",
                ),
                names,
                handoff="/csm-skill-update",
            ))

    # --- Warning: drift vs upstream baseline ------------------------------- #
    for s in skills:
        if not s["link_ok"] or not s["skillmd_present"]:
            continue
        drift = check_drift(s)
        s["drift"] = drift
        if drift and drift["differs"]:
            bump(s, "warning")
            warning.append(make_finding(
                "drift",
                "Drift from upstream baseline",
                "%s differs from its recorded upstream baseline "
                "(references/upstream-baseline.md) by %d line(s). This is expected if "
                "you intentionally forked/customized it; review if you didn't."
                % (s["install_name"], drift["changed_lines"]),
                [s["install_name"]],
                handoff=None,
            ))

    # --- Info: orphaned files & directories in ~/.claude/skills ----------- #
    for of in orphaned_files:
        info.append(make_finding(
            "orphaned_file",
            "Orphaned file in ~/.claude/skills",
            "%s (%s) is a loose file in the skills directory, not a skill folder. "
            "It is ignored by Claude Code and can likely be removed." % (of["path"], of["size"]),
            [of["name"]],
            handoff=None,
        ))
    for od in orphaned_dirs:
        info.append(make_finding(
            "orphaned_dir",
            "Orphaned directory in ~/.claude/skills",
            "%s (%s) is a directory with no SKILL.md — not a skill (often leftover "
            "support files like data/ or scripts/ from an old flat install). It is "
            "ignored by Claude Code and can likely be removed." % (od["path"], od["size"]),
            [od["name"]],
            handoff=None,
        ))

    # --- Info: orphaned clones -------------------------------------------- #
    orphaned_clones = find_orphaned_clones(skills, errors)
    for oc in orphaned_clones:
        info.append(make_finding(
            "orphaned_clone",
            "Orphaned clone in ~/.agents/skills",
            "%s (%s) is a cloned skill repo that no active ~/.claude/skills symlink "
            "points into. It occupies disk but isn't installed." % (oc["path"], oc["size"]),
            [oc["name"]],
            handoff=None,
        ))

    # --- Info: storage footprint ------------------------------------------ #
    footprint = []
    if AGENTS_SKILLS.exists():
        for child in sorted(AGENTS_SKILLS.iterdir()):
            if child.is_dir():
                footprint.append({"name": child.name, "kb": du_kb(str(child))})
    total_kb = sum(f["kb"] for f in footprint if f["kb"] is not None) or 0
    footprint.sort(key=lambda f: (f["kb"] or 0), reverse=True)
    storage = {
        "root": str(AGENTS_SKILLS),
        "total": human_size(total_kb),
        "total_kb": total_kb,
        "by_repo": [{"name": f["name"], "size": human_size(f["kb"])} for f in footprint],
    }
    info.append(make_finding(
        "storage",
        "Storage footprint",
        "Skill clones under %s use %s across %d repo(s)."
        % (AGENTS_SKILLS, storage["total"], len(footprint)),
        [],
        handoff=None,
    ))

    # --- Info: suite version ---------------------------------------------- #
    suite_root = git_toplevel(str(Path(__file__).resolve().parent))
    suite = {"name": "ClaudeSkillManager", "repo_path": suite_root,
             "version": None, "commit_date": None}
    if suite_root:
        ver, _, _ = run("git log -1 --format=%h", cwd=suite_root)
        cdate, _, _ = run("git log -1 --format=%ci", cwd=suite_root)
        suite["version"] = ver or None
        suite["commit_date"] = cdate or None
    info.append(make_finding(
        "suite_version",
        "Suite version",
        "ClaudeSkillManager @ %s (%s)" % (suite["version"] or "unknown",
                                          suite["commit_date"] or "unknown date"),
        [],
        handoff=None,
    ))

    # --- Health score ------------------------------------------------------ #
    n_crit, n_warn, n_info = len(critical), len(warning), len(info)
    score = max(0, 100 - SCORE_CRITICAL * n_crit - SCORE_WARNING * n_warn - SCORE_INFO * n_info)
    letter, label = grade_for(score)

    output = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "suite": suite,
        "scan_roots": [str(p) for p in SCAN_ROOTS],
        "fetched": do_fetch,
        "health": {"score": score, "grade": letter, "label": label},
        "counts": {
            "skills": len(skills),
            "critical": n_crit,
            "warning": n_warn,
            "info": n_info,
        },
        "scoring": {
            "per_critical": -SCORE_CRITICAL,
            "per_warning": -SCORE_WARNING,
            "per_info": -SCORE_INFO,
            "note": "score = max(0, 100 - 25*critical - 8*warning); info does not reduce score",
        },
        "storage": storage,
        "skills": sorted(skills, key=lambda s: s["install_name"]),
        "findings": {
            "critical": critical,
            "warning": warning,
            "info": info,
        },
        "errors": errors,
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
