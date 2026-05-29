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

There are two layers, kept distinct in the JSON:
  * STANDARD AUDIT (always) — health / git / symlinks → top-level "health",
    "findings", "skills", "storage".
  * DEEP SECURITY SCAN (only with --scan) — content analysis of each skill's
    SKILL.md and scripts against shared/security-patterns.md → top-level
    "security" (per-skill + overall security scores and findings).

Usage
-----
  python3 audit.py             # standard audit (fetches remotes to check "behind")
  python3 audit.py --no-fetch  # skip network fetches; "behind" becomes unknown
  python3 audit.py --scan      # standard audit PLUS the deep security scan
  python3 audit.py --list      # inventory mode: just list installed skills (no fetch)

Output: pretty-printed JSON on stdout. Non-fatal problems are collected under
the top-level "errors" array rather than crashing the run.
"""

import argparse
import difflib
import json
import os
import re
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


def human_bytes(n):
    """Render a byte count as a human-readable string."""
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0 or unit == "GB":
            return "%d %s" % (int(size), unit) if unit == "B" else "%.1f %s" % (size, unit)
        size /= 1024.0
    return "%.1f GB" % size


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


def read_activity():
    """Read ~/.csm/csm.log (JSON Lines) and summarize recent suite activity.

    Read-only. Returns the most-recent install, update check, and security scan
    so the audit can show a "Suite Activity" header. Entries are appended in
    chronological order, so iterating and overwriting keeps the latest of each.
    """
    log_file = Path.home() / ".csm" / "csm.log"
    info = {
        "log_path": str(log_file),
        "log_exists": log_file.is_file(),
        "entries": 0,
        "last_install": None,
        "last_update_check": None,
        "last_security_scan": None,
        "last_rollback": None,
        "last_removal": None,
    }
    if not info["log_exists"]:
        return info
    try:
        lines = log_file.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return info
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue  # skip malformed lines, keep going
        info["entries"] += 1
        action = e.get("action", "")
        ts = e.get("timestamp", "") or ""
        date = ts[:10]
        if action in ("installed", "reinstalled"):
            info["last_install"] = {"skill": e.get("skill"), "date": date,
                                    "action": action, "timestamp": ts}
        elif action == "checked":
            info["last_update_check"] = {"date": date, "timestamp": ts,
                                         "details": e.get("details", "")}
        elif action == "scan-run":
            # Prefer the structured field; fall back to parsing the details text
            # only for older log entries written before the field existed.
            ss = e.get("skills_scanned")
            if not isinstance(ss, int) or isinstance(ss, bool):
                m = re.search(r"(\d+)\s+skill", e.get("details", "") or "")
                ss = int(m.group(1)) if m else None
            info["last_security_scan"] = {
                "date": date, "timestamp": ts,
                "skills_scanned": ss,
                "details": e.get("details", ""),
            }
        elif action == "rolled-back":
            info["last_rollback"] = {
                "skill": e.get("skill"), "date": date, "timestamp": ts,
                "to_commit": e.get("to_commit"), "from_commit": e.get("from_commit"),
                "details": e.get("details", ""),
            }
        elif action == "uninstalled":
            info["last_removal"] = {
                "skill": e.get("skill"), "date": date, "timestamp": ts,
                "clone_removed": e.get("clone_removed"),
                "bundle_removed": e.get("bundle_removed"),
                "details": e.get("details", ""),
            }
    return info


# --------------------------------------------------------------------------- #
# Deep security scan (--scan): static content analysis of each installed skill
# against the patterns documented in shared/security-patterns.md.
#
# This is mechanical pattern-matching that produces *candidate* findings with
# enough context (file, line, snippet) for Claude to apply judgment — e.g.
# "shell execution on UNTRUSTED input" is the truly-critical case, which Claude
# decides from the snippet. Documentation/comment/string mentions of a code
# pattern (a *mention* of `subprocess`, not an *invocation*) are demoted to
# info so security tooling and docs don't trip false criticals.
# --------------------------------------------------------------------------- #
SEC_CRITICAL = 20
SEC_WARNING = 8
SEC_INFO = 1
SEVERITY_WEIGHT = {"critical": SEC_CRITICAL, "warning": SEC_WARNING, "info": SEC_INFO}

SCRIPT_EXTS = {".py", ".sh", ".bash", ".zsh", ".js", ".mjs", ".cjs",
               ".ts", ".tsx", ".rb", ".pl", ".php", ".ps1"}
MANIFEST_NAMES = {"package.json", "requirements.txt", "pyproject.toml",
                  "pipfile", "gemfile"}
MAX_FILE_BYTES = 512 * 1024
MAX_FILES_PER_SKILL = 200
MAX_MATCHES_PER_CAT_PER_FILE = 8

# Categories describing INSTRUCTIONS to Claude live naturally in prose, so they
# keep their severity even in markdown. CODE-behavior categories are demoted
# when the match is inert (comment / string literal / documentation).
INSTRUCTION_CATS = {"permission_change", "scope_expansion"}

# (category, base_severity, regex) — mirrors shared/security-patterns.md.
_PATTERN_DEFS = [
    # ---- Critical: high-priority code behavior ----
    # Target actual invocations, not imports/exception names or JS `.exec()`
    # regex-method calls (the bare `exec(`/`eval(` use a lookbehind to skip a
    # leading dot or word char, so `foo.exec(` / `regex.exec(` don't match).
    ("shell_execution", "critical",
     r"subprocess\.(?:run|call|Popen|check_output|check_call|getoutput)"
     r"|\bos\.system\s*\(|\bos\.popen\s*\(|\bos\.exec\w*\s*\(|\bpty\.spawn\b"
     r"|shell\s*=\s*True|child_process|\bexecSync\b|\bspawnSync\b|\bexecFileSync\b"
     r"|(?<![.\w])eval\s*\(|(?<![.\w])exec\s*\("),
    ("destructive_command", "critical",
     r"\brm\s+-[rf]{1,2}\b|\bsudo\b|\bmkfs\b|\bchmod\s+777\b|\bchown\s+-R\b|>\s*/dev/sd"),
    # `(?<![\w.])\.env\b` matches a literal .env file but NOT `process.env` /
    # `os.environ` (those are env access — caught as a warning below).
    ("credential_harvesting", "critical",
     r"~/\.ssh|~/\.aws|\.aws/credentials|\bid_rsa\b|\bAPI_KEY\b|\bAPIKEY\b|\bSECRET_KEY\b"
     r"|\bACCESS_TOKEN\b|\bAUTH_TOKEN\b|\bPRIVATE_KEY\b|\bPASSWORD\b|(?<![\w.])\.env\b|\bnetrc\b"),
    ("obfuscation", "critical",
     r"\bbase64\b|\batob\b|\bbtoa\b|\bb64decode\b|\bb64encode\b|codecs\.decode"
     r"|fromCharCode|(?:\\x[0-9a-fA-F]{2}){4,}"),
    # ---- Warning: medium-priority behavior / scope ----
    ("network", "warning",
     r"\bcurl\b|\bwget\b|requests\.(?:get|post|put|request)|\bfetch\s*\("
     r"|\baxios\b|urllib\.request|http\.client|new\s+WebSocket|socket\.socket"),
    ("filesystem_scope", "warning",
     r"~/\.claude\b|~/\.config\b|\bshutil\.(?:move|copy|copytree|rmtree)\b"
     r"|\bos\.remove\b|\bos\.rename\b|open\([^)]*['\"]/(?:etc|usr|var|bin)/"),
    ("env_access", "warning",
     r"\bos\.environ\b|process\.env\b|\bgetenv\b"),
    ("permission_change", "warning",
     r"without asking|without confirmation|do not ask|don'?t ask|no confirmation"
     r"|skip(?:ping)? confirmation|auto-?(?:apply|execute|run|confirm)"),
    ("scope_expansion", "warning",
     r"browser (?:history|cookies)|local ?storage|other skills'? files|read[^.\n]{0,40}cookies"),
    ("external_url", "warning",
     r"https?://(?!github\.com|raw\.githubusercontent\.com|api\.github\.com|docs\."
     r"|registry\.npmjs\.org|pypi\.org|developer\.mozilla\.org|www\.w3\.org|schema\.org)"
     r"[A-Za-z0-9.\-]+"),
    # ---- Info: low-priority / informational ----
    ("doc_or_public_api", "info",
     r"https?://(?:github\.com|raw\.githubusercontent\.com|api\.github\.com|docs\."
     r"|registry\.npmjs\.org|pypi\.org|developer\.mozilla\.org)"),
]
_PATTERNS = [(c, s, re.compile(rx, re.IGNORECASE)) for c, s, rx in _PATTERN_DEFS]

_CATEGORY_NOTES = {
    "shell_execution": "Shell/dynamic execution — confirm the input is fixed/trusted, not user- or network-controlled.",
    "destructive_command": "Destructive command — flag regardless of context.",
    "credential_harvesting": "Touches secrets/credentials — verify it isn't reading or exfiltrating them.",
    "obfuscation": "Encoded/obfuscated content — decode and verify intent.",
    "network": "Network call — verify the destination and that no local data is sent.",
    "filesystem_scope": "Operates outside the skill directory — verify the scope.",
    "env_access": "Reads environment variables — verify which ones and why.",
    "permission_change": "Instruction to act without confirmation — verify it is appropriate.",
    "scope_expansion": "Accesses browser / other-skill / project data — verify necessity.",
    "external_url": "Non-allowlisted external URL — verify the destination.",
    "doc_or_public_api": "Documentation link or well-known public API — informational.",
}


def sec_grade(score):
    """Map a 0-100 security score to (letter, label)."""
    if score >= 90:
        return "A", "Clean"
    if score >= 75:
        return "B", "Low risk"
    if score >= 60:
        return "C", "Some concerns"
    if score >= 40:
        return "D", "Elevated risk"
    return "F", "High risk"


def _sev_rank(sev):
    return {"critical": 3, "warning": 2, "info": 1}.get(sev, 0)


def _is_suite_skill(remote):
    return bool(remote) and "ClaudeSkillManager" in remote


def _looks_inert(line, mstart):
    """True if a match is documentation/comment/string-literal, not live code."""
    stripped = line.lstrip()
    for c in ("#", "//", "*", "<!--", "- ", "> "):
        if stripped.startswith(c):
            return True
    prefix = line[:mstart]
    for q in ("'", '"', "`"):
        if prefix.count(q) % 2 == 1:  # the token sits inside an open quote
            return True
    low = line.lower()
    for k in ("re.compile", "r'", 'r"', "regex", "pattern", "flag the",
              "flag any", "always flag", "watch for", "concern"):
        if k in low:
            return True
    return False


def _iter_scan_files(skill_dir):
    """Yield (abspath, relpath, kind) for SKILL.md, scripts, and manifests."""
    seen = set()
    count = 0
    for root, dirs, files in os.walk(skill_dir, followlinks=True):
        dirs[:] = [d for d in dirs if d != ".git"]
        rroot = os.path.realpath(root)
        if rroot in seen:
            dirs[:] = []
            continue
        seen.add(rroot)
        for fn in sorted(files):
            low = fn.lower()
            if low == "skill.md":
                kind = "markdown"
            elif low in MANIFEST_NAMES:
                kind = "manifest"
            elif os.path.splitext(fn)[1].lower() in SCRIPT_EXTS:
                kind = "script"
            else:
                continue
            ap = os.path.join(root, fn)
            try:
                if os.path.getsize(ap) > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            yield ap, os.path.relpath(ap, skill_dir), kind
            count += 1
            if count >= MAX_FILES_PER_SKILL:
                return


def _scan_complexity(files, total_bytes):
    """Rough estimate of how heavy a skill is to scan/interpret."""
    if files >= 8 or total_bytes > 150 * 1024:
        return "high"
    if files <= 2 and total_bytes <= 30 * 1024:
        return "low"
    return "medium"


def compute_scan_preview(skill_dir):
    """Cheap (stat-only) preview of what a security scan would read for a skill.

    Used by the standard audit so the pre-scan prompt can show sizes, script
    counts and an estimated complexity *without* reading any content yet.
    """
    skillmd_bytes = 0
    scripts = 0
    files = 0
    total_bytes = 0
    for ap, _rp, kind in _iter_scan_files(skill_dir):
        try:
            sz = os.path.getsize(ap)
        except OSError:
            sz = 0
        files += 1
        total_bytes += sz
        if kind == "markdown" and os.path.basename(ap).lower() == "skill.md":
            skillmd_bytes += sz
        if kind == "script":
            scripts += 1
    return {
        "files": files,
        "scripts": scripts,
        "skillmd_bytes": skillmd_bytes,
        "skillmd_size": human_bytes(skillmd_bytes),
        "total_bytes": total_bytes,
        "total_size": human_bytes(total_bytes),
        "complexity": _scan_complexity(files, total_bytes),
    }


def _scan_file(ap, rp, kind, findings):
    """Append security findings discovered in one file."""
    try:
        with open(ap, "r", encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
    except OSError:
        return
    if kind == "manifest":
        findings.append({
            "category": "external_dependency", "severity": "info",
            "base_severity": "info", "prose": False, "file": rp, "line": 1,
            "snippet": "declares external dependencies (%s)" % os.path.basename(ap),
            "note": "Declares third-party dependencies; review changes in diffs via /csm-skill-update.",
        })
        return
    per_cat = {}
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw[:4000]
        for cat, base_sev, rx in _PATTERNS:
            m = rx.search(line)
            if not m:
                continue
            key = (cat, rp)
            if per_cat.get(key, 0) >= MAX_MATCHES_PER_CAT_PER_FILE:
                continue
            per_cat[key] = per_cat.get(key, 0) + 1
            inert = (kind == "markdown") or _looks_inert(line, m.start())
            if cat in INSTRUCTION_CATS:
                eff = base_sev
            elif inert:
                eff = "info"
            else:
                eff = base_sev
            findings.append({
                "category": cat,
                "severity": eff,
                "base_severity": base_sev,
                "prose": bool(inert),
                "file": rp,
                "line": lineno,
                "snippet": line.strip()[:160],
                "note": _CATEGORY_NOTES.get(cat, ""),
            })


def run_security_scan(skills, patterns_source, patterns_loaded, only=None):
    """Scan each installed skill's content; return the security report dict.

    `only` (optional set of install names) limits the scan to those skills, so
    a user can scan specific skills instead of the whole library.
    """
    sec_skills = []
    tot_c = tot_w = tot_i = files_total = flagged = 0
    for s in skills:
        if not s["link_ok"] or not s["skillmd_present"]:
            continue  # can't read content of a broken/empty skill
        if only is not None and s["install_name"] not in only:
            continue  # scoped scan: skip skills not requested
        findings = []
        nfiles = 0
        for ap, rp, kind in _iter_scan_files(s["real_path"]):
            nfiles += 1
            _scan_file(ap, rp, kind, findings)
        c = sum(1 for f in findings if f["severity"] == "critical")
        w = sum(1 for f in findings if f["severity"] == "warning")
        i = sum(1 for f in findings if f["severity"] == "info")
        deduction = sum(SEVERITY_WEIGHT[f["severity"]] for f in findings)
        score = max(0, 100 - deduction)
        grade, label = sec_grade(score)
        git = s.get("git") or {}
        behind = git.get("commits_behind")
        sec_skills.append({
            "install_name": s["install_name"],
            "score": score, "grade": grade, "label": label,
            "files_scanned": nfiles,
            "counts": {"critical": c, "warning": w, "info": i},
            "commits_behind": behind,
            "pending_update": isinstance(behind, int) and behind > 0,
            "is_suite_skill": _is_suite_skill(git.get("remote")),
            "findings": sorted(findings, key=lambda f: (_sev_rank(f["severity"]),
                                                        not f["prose"]), reverse=True),
        })
        tot_c += c
        tot_w += w
        tot_i += i
        files_total += nfiles
        if c or w:
            flagged += 1
    scanned = len(sec_skills)
    overall = round(sum(x["score"] for x in sec_skills) / scanned) if scanned else 100
    ogr, olab = sec_grade(overall)
    return {
        "ran": True,
        "scope": "selected" if only is not None else "all",
        "requested": sorted(only) if only is not None else None,
        "patterns_source": patterns_source,
        "patterns_loaded": patterns_loaded,
        "overall_score": overall,
        "overall_grade": ogr,
        "overall_label": olab,
        "counts": {"skills_scanned": scanned, "skills_flagged": flagged,
                   "files_scanned": files_total,
                   "critical": tot_c, "warning": tot_w, "info": tot_i},
        "scoring": {
            "per_critical": -SEC_CRITICAL, "per_warning": -SEC_WARNING, "per_info": -SEC_INFO,
            "note": "per-skill = max(0, 100 - 20*critical - 8*warning - 1*info); overall = "
                    "mean of per-skill scores. Doc/comment/string mentions of code patterns "
                    "are demoted to info (prose=true), so a *mention* of a pattern isn't a "
                    "critical. Claude still confirms genuine risk from each snippet.",
        },
        "skills": sorted(sec_skills, key=lambda x: x["score"]),
    }


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
def _new_skill(name, link_path, real_path, is_symlink, link_ok, skillmd_present, skill_md):
    return {
        "install_name": name,
        "declared_name": read_declared_name(skill_md) if skillmd_present else None,
        # All currently-scanned skills live under ~/.claude/skills (user-global).
        # Reserved for a future expansion that also scans project-scoped paths
        # (<project>/.claude/skills); values will be "user" or "project" then.
        "scope": "user",
        "link_path": link_path,
        "real_path": real_path,
        "is_symlink": is_symlink,
        "link_ok": link_ok,
        "skillmd_present": skillmd_present,
        # git/drift/preview fields filled in later
        "git": None,
        "drift": None,
        "scan_preview": None,
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


_CLONE_SHAPE_PRUNE = {".git", "node_modules", "__pycache__", ".venv",
                      "dist", "build", ".next", ".cache"}


def _is_clone_shaped(path):
    """Cheap check: does this dir look like a *skill clone*?

    A skill clone has a `.git` entry AND a `SKILL.md` in one of the known
    skill-repo layouts: root, a direct child folder (e.g. ClaudeSkillManager's
    `csm-skill-*/SKILL.md`), `skills/<name>/SKILL.md`, or
    `.claude/skills/<name>/SKILL.md`. This deliberately ignores `SKILL.md`
    nested arbitrarily deep — that's how a foreign project that happens to
    *contain* a skill bundle (rather than *be* one) gets correctly filtered
    out.
    """
    if not (path / ".git").exists():
        return False
    if (path / "SKILL.md").is_file():
        return True
    # Direct child subfolders (single-folder-per-skill repos, e.g. csm-*).
    try:
        for child in path.iterdir():
            if not child.is_dir() or child.name in _CLONE_SHAPE_PRUNE:
                continue
            if (child / "SKILL.md").is_file():
                return True
    except OSError:
        pass
    # Conventional nested layouts.
    for nested in (path / "skills", path / ".claude" / "skills"):
        if not nested.is_dir():
            continue
        try:
            for sub in nested.iterdir():
                if sub.is_dir() and (sub / "SKILL.md").is_file():
                    return True
        except OSError:
            continue
    return False


def find_orphaned_clones(skills, extra_scan_roots, errors):
    """Skill clones anywhere we know to look that no active skill links into.

    Scan roots are the union of:
      * `~/.agents/skills/` (the suite's install convention; always included).
      * Any `--scan-roots` paths the user passed.
      * The *parent* of every repo root that backs an active skill — so if you
        keep a clone under a projects directory (e.g. `~/ClaudeProjects/...`),
        sibling clones there are scanned too without configuration.

    Only entries that look like a skill clone (`.git` + a nested `SKILL.md`)
    are considered; ordinary project directories that happen to share a parent
    are filtered out so they never become false-positive orphans.
    """
    orphans = []
    referenced = [s["real_path"] for s in skills if s["link_ok"]]

    roots = set()
    roots.add(AGENTS_SKILLS)
    for raw in extra_scan_roots or ():
        roots.add(Path(raw).expanduser())
    for rp in referenced:
        top = git_toplevel(rp)
        if not top:
            continue
        roots.add(Path(top).parent)

    seen_paths = set()
    for root in sorted(roots, key=lambda p: str(p)):
        if not root.exists() or not root.is_dir():
            continue
        try:
            children = sorted(root.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir():
                continue
            try:
                base = str(child.resolve())
            except OSError:
                continue
            if base in seen_paths:
                continue
            seen_paths.add(base)
            if not _is_clone_shaped(child):
                continue
            used = any(rp == base or rp.startswith(base + os.sep) for rp in referenced)
            if used:
                continue
            orphans.append({
                "path": str(child),
                "name": child.name,
                "scan_root": str(root),
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
    parser.add_argument("--scan", action="store_true",
                        help="Also run the deep security scan (content analysis of "
                             "each skill's SKILL.md and scripts).")
    parser.add_argument("--skills", default=None,
                        help="Comma-separated install names to limit --scan to "
                             "(e.g. --skills impeccable,ui-ux-pro-max). Default: all.")
    parser.add_argument("--list", dest="list_mode", action="store_true",
                        help="Inventory mode: just list installed skills (no fetch, "
                             "no findings render). Output JSON gains `view: \"list\"`; "
                             "the SKILL.md presents only the roster from skills[].")
    parser.add_argument("--scan-roots", default=None,
                        help="Comma-separated extra directories to scan for "
                             "orphaned skill clones. The default scan roots are "
                             "~/.agents/skills/ (the install convention) plus the "
                             "parents of any repos backing active skills "
                             "(auto-derived). Use this to explicitly add more.")
    args = parser.parse_args()
    extra_scan_roots = []
    if args.scan_roots:
        extra_scan_roots = [p.strip() for p in args.scan_roots.split(",") if p.strip()]
    # --list implies --no-fetch (we're not asking about updates).
    do_fetch = not args.no_fetch and not args.list_mode
    only = None
    if args.skills:
        only = set(x.strip() for x in args.skills.split(",") if x.strip())

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
    orphaned_clones = find_orphaned_clones(skills, extra_scan_roots, errors)
    for oc in orphaned_clones:
        info.append(make_finding(
            "orphaned_clone",
            "Orphaned skill clone",
            "%s (%s) is a cloned skill repo (found under %s) that no active "
            "~/.claude/skills symlink points into. It occupies disk but isn't "
            "installed." % (oc["path"], oc["size"], oc["scan_root"]),
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

    # --- Pre-scan preview (cheap stat-only sizing for the scan prompt) ----- #
    # Lets the end-of-audit prompt show per-skill size / script count /
    # estimated complexity *before* any content is read.
    for s in skills:
        if s["link_ok"] and s["skillmd_present"]:
            s["scan_preview"] = compute_scan_preview(s["real_path"])
    _previews = [s["scan_preview"] for s in skills if s.get("scan_preview")]
    _pv_bytes = sum(p["total_bytes"] for p in _previews)
    scan_preview = {
        "skills": len(_previews),
        "files": sum(p["files"] for p in _previews),
        "scripts": sum(p["scripts"] for p in _previews),
        "total_bytes": _pv_bytes,
        "total_size": human_bytes(_pv_bytes),
    }

    # --- Health score ------------------------------------------------------ #
    n_crit, n_warn, n_info = len(critical), len(warning), len(info)
    score = max(0, 100 - SCORE_CRITICAL * n_crit - SCORE_WARNING * n_warn - SCORE_INFO * n_info)
    letter, label = grade_for(score)

    # --- Deep security scan (content analysis) — only with --scan ---------- #
    sec_source = None
    sec_loaded = False
    if suite_root:
        sec_source = os.path.join(suite_root, "shared", "security-patterns.md")
        sec_loaded = os.path.isfile(sec_source)
    if args.scan:
        security = run_security_scan(skills, sec_source, sec_loaded, only=only)
    else:
        security = {
            "ran": False,
            "hint": "Run `audit.py --scan` (or accept the end-of-audit prompt) to "
                    "deep-scan each skill's content against shared/security-patterns.md. "
                    "Add --skills name1,name2 to scan only specific skills.",
        }

    output = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "view": "list" if args.list_mode else "full",
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
        "scan_preview": scan_preview,
        "activity": read_activity(),
        "skills": sorted(skills, key=lambda s: s["install_name"]),
        "findings": {
            "critical": critical,
            "warning": warning,
            "info": info,
        },
        "security": security,
        "errors": errors,
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
