#!/usr/bin/env python3
"""
tooling/preflight.py

Local preflight for the eds-skills pipeline (EDS-11). It covers the smoke-test
assertions that CI cannot make because they are about Brad's machine, checkout
and token rather than the repo. Run it in WSL, from the repo root, before
starting ticket work:

    python3 tooling/preflight.py                 # all checks, fetches origin
    python3 tooling/preflight.py --no-fetch      # no network fetch (CI-like, shallow clones)
    python3 tooling/preflight.py --repo owner/name
    python3 tooling/preflight.py --skip pr-write,ruleset

It prints one line per check ([PASS] / [FAIL] / [WARN] / [SKIP] / [INFO]) with a
short reason and, where useful, the exact fix, then a summary. The exit code is
1 only if a check FAILed; WARN, SKIP and INFO never fail the run. It is
read-only (the one GitHub write probe is built to be rejected, see pr-write)
and never prints tokens or secrets: every line passes through redact().

Checks (the id is what --skip takes; the ticket is where the gap was found):

  python    EDS-14  python3 runs (>= 3.10 suggested); WARN if PyYAML is missing
                    (skill-create/test.py and CI need it).
  git-repo  EDS-18  the current directory is a git repo.
  git-locks EDS-18  no *.lock files under .git (WARN with the path; a zero-byte
                    maintenance.lock did not block git in EDS-18).
  git-fresh EDS-18  after `git fetch origin` (unless --no-fetch): on main equal
                    to origin/main, or on a branch whose merge-base with
                    origin/main is origin/main's tip; else FAIL (behind).
  git-clean EDS-18  working tree clean (WARN if not).
  gh-auth   EDS-20  gh is installed and authenticated (`gh auth status`; its
                    output is discarded, so the token is never shown).
  pr-write  EDS-20  a deliberately invalid PR create (nonexistent head branch)
                    must be rejected with HTTP 422 validation, which proves the
                    token may create PRs and creates nothing. HTTP 403 "Resource
                    not accessible by personal access token" is a FAIL.
  ruleset   EDS-40  rules/branches/main has a required_status_checks rule that
                    lists the context `check` (SKIP if the API is unreadable).
  notion    EDS-24  SKIP: needs a Notion token; a manual or agent-run check.
  merge     EDS-21  INFO: not automatable; merges stay human.
  install   EDS-23  INFO: not automatable; Cowork install is manual.

Standard library only. Tests: tooling/test_preflight.py (also run by
tooling/test_package_skill.py, so CI covers them).
"""
import argparse
import json
import os
import re
import subprocess
import sys

PASS, FAIL, WARN, SKIP, INFO = "PASS", "FAIL", "WARN", "SKIP", "INFO"

CHECK_IDS = ("python", "git-repo", "git-locks", "git-fresh", "git-clean",
             "gh-auth", "pr-write", "ruleset", "notion", "merge", "install")

REQUIRED_CONTEXT = "check"  # Skill PR Check's job name in the required-checks rule


def run(cmd, cwd=None, timeout=60):
    """The only place subprocesses are started; tests stub this.
    Returns (returncode, stdout, stderr). Never raises."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GH_PROMPT_DISABLED="1")
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True,
                           timeout=timeout)
    except FileNotFoundError:
        return 127, "", f"{cmd[0]}: command not found"
    except OSError as e:  # e.g. PermissionError when PATH has unreadable entries (WSL)
        return 127, "", f"{cmd[0]}: command not found or not runnable ({e.strerror})"
    except subprocess.TimeoutExpired:
        return 124, "", f"{cmd[0]}: timed out after {timeout}s"
    return p.returncode, p.stdout, p.stderr


_SECRET_PATTERNS = (
    (re.compile(r"(github_pat_|gh[pousr]_|glpat-|secret_|ntn_)[A-Za-z0-9_]+"), "***"),
    (re.compile(r"(?i)(token\s*[:=]\s*)[A-Za-z0-9_.*-]{16,}"), r"\1***"),
    (re.compile(r"(?i)(authorization:\s*)\S+(\s+\S+)?"), r"\1***"),
    (re.compile(r"://[^/@\s]+@"), "://***@"),
)


def redact(text):
    for pattern, repl in _SECRET_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def first_line(text, limit=160):
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:limit]
    return ""


def have_module(name):
    try:
        __import__(name)
        return True
    except ImportError:
        return False


# --- EDS-14 -----------------------------------------------------------------

def check_python():
    v = sys.version_info
    version = f"{v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) < (3, 10):
        return WARN, f"python3 {version} runs, but 3.10+ is suggested"
    if not have_module("yaml"):
        return WARN, (f"python3 {version} runs, but PyYAML is not importable "
                      "(skill-create/test.py and CI need it): pip install pyyaml")
    return PASS, f"python3 {version}, PyYAML importable"


# --- EDS-18 -----------------------------------------------------------------

def check_git_repo():
    rc, out, _ = run(["git", "rev-parse", "--is-inside-work-tree"])
    if rc != 0 or out.strip() != "true":
        return FAIL, "not inside a git repo: cd to the eds-skills checkout (run from the repo root)"
    rc, out, _ = run(["git", "rev-parse", "--show-toplevel"])
    return PASS, f"git repo at {out.strip()}" if rc == 0 else "git repo"


def find_locks(git_dir):
    """Every *.lock file under git_dir as (path, size)."""
    found = []
    for root, _dirs, files in os.walk(git_dir):
        for name in files:
            if name.endswith(".lock"):
                path = os.path.join(root, name)
                try:
                    size = os.path.getsize(path)
                except OSError:
                    size = -1
                found.append((path, size))
    return sorted(found)


def check_git_locks():
    rc, out, _ = run(["git", "rev-parse", "--git-common-dir"])
    if rc != 0:
        return SKIP, "not a git repo"
    git_dir = os.path.abspath(out.strip())
    locks = find_locks(git_dir)
    if not locks:
        return PASS, "no *.lock files under .git"
    items = ", ".join(f"{p} ({'empty' if s == 0 else str(s) + ' bytes'})" for p, s in locks)
    harmless = all(os.path.basename(p) == "maintenance.lock" and s == 0 for p, s in locks)
    note = ("a zero-byte maintenance.lock did not block git in EDS-18"
            if harmless else "a stale lock can block git operations")
    return WARN, f"{items}; {note}. If no git process is running: rm <path>"


def _count(range_spec):
    rc, out, _ = run(["git", "rev-list", "--count", range_spec])
    return int(out.strip()) if rc == 0 and out.strip().isdigit() else None


def check_git_fresh(fetch=True):
    note = ""
    if fetch:
        rc, _, err = run(["git", "fetch", "origin"], timeout=120)
        if rc != 0:
            return WARN, f"git fetch origin failed ({first_line(redact(err))}); cannot verify freshness"
    else:
        note = " (not fetched: --no-fetch, using the last known origin/main)"
    rc, tip, _ = run(["git", "rev-parse", "origin/main"])
    if rc != 0:
        return FAIL, "no origin/main ref: git fetch origin"
    tip = tip.strip()
    rc, head, _ = run(["git", "rev-parse", "HEAD"])
    if rc != 0:
        return FAIL, "HEAD does not resolve (no commits?)"
    head = head.strip()
    _, branch, _ = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    branch = branch.strip()
    fix = "branch from a freshly fetched origin/main: git fetch origin; git checkout -b <type>/EDS-<n>-<name> origin/main"

    if branch == "main":
        if head == tip:
            return PASS, "on main, equal to origin/main (do not work on main: branch off it)" + note
        behind = _count("HEAD..origin/main")
        ahead = _count("origin/main..HEAD")
        if behind:
            return FAIL, f"main is behind origin/main by {behind}: {fix}"
        if ahead:
            return WARN, f"main has {ahead} commit(s) not on origin/main (never commit to main)"
        return WARN, "main differs from origin/main; cannot count commits (shallow clone?)"

    rc, mb, _ = run(["git", "merge-base", "HEAD", "origin/main"])
    label = "detached HEAD" if branch == "HEAD" else f"branch {branch}"
    if rc != 0:
        return WARN, f"{label}: no merge-base with origin/main (shallow clone? unrelated history?)"
    if mb.strip() == tip:
        return PASS, f"{label} is cut from the current origin/main tip" + note
    behind = _count(f"{mb.strip()}..origin/main")
    n = str(behind) if behind is not None else "some commits"
    return FAIL, f"{label} is behind origin/main by {n}: {fix}"


def check_git_clean():
    rc, out, _ = run(["git", "status", "--porcelain"])
    if rc != 0:
        return SKIP, "git status failed"
    lines = [l for l in out.splitlines() if l.strip()]
    if not lines:
        return PASS, "working tree clean"
    return WARN, f"working tree has {len(lines)} uncommitted change(s): commit or stash before branching"


# --- EDS-20 -----------------------------------------------------------------

def check_gh_auth():
    rc, _out, err = run(["gh", "auth", "status"])
    # Output is discarded on success: gh prints a masked token prefix.
    if rc == 127:
        return FAIL, "gh not found: install the GitHub CLI in WSL (the Windows host has none)"
    if rc != 0:
        return FAIL, "gh is not authenticated: set GITHUB_TOKEN or run gh auth login (do not paste tokens into chat)"
    return PASS, "gh is installed and authenticated"


def check_pr_write(repo):
    if not repo:
        return SKIP, "repo unknown (no origin remote): pass --repo owner/name"
    rc, out, err = run(["gh", "api", f"repos/{repo}/pulls", "-X", "POST",
                        "-f", "title=preflight", "-f", "head=preflight-nonexistent-branch",
                        "-f", "base=main"])
    text = redact(out + "\n" + err)
    if rc == 127:
        return SKIP, "gh not found"
    if rc == 0:
        return FAIL, ("UNEXPECTED: the invalid PR probe succeeded, so a PR may have been created on "
                      f"{repo}: check `gh pr list` and close it")
    if re.search(r"HTTP 422|\b422\b", text) and "Validation Failed" in text:
        return PASS, "PR create probe rejected with HTTP 422 validation: the token may create PRs"
    if "Resource not accessible" in text or re.search(r"HTTP 403|\b403\b", text):
        return FAIL, (f"HTTP 403 Resource not accessible by personal access token: the token lacks "
                      f"'Pull requests: Read and write' on {repo}; ask Brad to add it")
    if re.search(r"HTTP 401|Bad credentials", text):
        return FAIL, "HTTP 401: the token is invalid or expired; ask Brad to renew it"
    if re.search(r"HTTP 404|Not Found", text):
        return FAIL, f"HTTP 404: the token cannot see {repo}; check --repo and the token's repository access"
    return WARN, f"inconclusive probe response: {first_line(text)}"


# --- EDS-40 -----------------------------------------------------------------

def check_ruleset(repo):
    if not repo:
        return SKIP, "repo unknown (no origin remote): pass --repo owner/name"
    rc, out, err = run(["gh", "api", f"repos/{repo}/rules/branches/main"])
    if rc != 0:
        return SKIP, f"rules API not readable ({first_line(redact(err or out))})"
    try:
        rules = json.loads(out)
    except ValueError:
        return SKIP, "rules API returned something that is not JSON"
    if not isinstance(rules, list):
        return SKIP, "rules API returned an unexpected shape"
    contexts = []
    for rule in rules:
        if isinstance(rule, dict) and rule.get("type") == "required_status_checks":
            params = rule.get("parameters") or {}
            for item in params.get("required_status_checks") or []:
                if isinstance(item, dict) and item.get("context"):
                    contexts.append(item["context"])
    if REQUIRED_CONTEXT in contexts:
        return PASS, f"main requires status check '{REQUIRED_CONTEXT}' (all: {', '.join(contexts)})"
    return FAIL, (f"main has no required status check '{REQUIRED_CONTEXT}' "
                  f"(found: {', '.join(contexts) or 'none'}): a ruleset setting for Brad (EDS-40)")


# --- EDS-24, 21, 23 ---------------------------------------------------------

def check_notion():
    return SKIP, ("Skills Library versions need a Notion token: manual or agent-run check (EDS-24); "
                  "compare each Skills Library entry's newest Version history line with skills/<name>/skill.json")


def check_merge():
    return INFO, ("EDS-21: not automatable. The desktop app's permission classifier blocks `gh pr merge` "
                  "by design; merges stay human (Brad)")


def check_install():
    return INFO, ("EDS-23: not automatable. Installing the .plugin in Cowork is manual, and a running "
                  "session will not see a newly installed skill: start a new session and invoke it")


# --- driver -----------------------------------------------------------------

def default_repo():
    """owner/name from the origin remote, or None. The URL itself is never shown."""
    rc, out, _ = run(["git", "remote", "get-url", "origin"])
    if rc != 0:
        return None
    m = re.search(r"github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?\s*$", out.strip())
    return f"{m.group(1)}/{m.group(2)}" if m else None


def run_checks(repo=None, fetch=True, skip=()):
    """Run the checks, return a list of (id, status, message)."""
    skip = set(skip)
    if repo is None:
        repo = default_repo()
    plan = [
        ("python", check_python),
        ("git-repo", check_git_repo),
        ("git-locks", check_git_locks),
        ("git-fresh", lambda: check_git_fresh(fetch)),
        ("git-clean", check_git_clean),
        ("gh-auth", check_gh_auth),
        ("pr-write", lambda: check_pr_write(repo)),
        ("ruleset", lambda: check_ruleset(repo)),
        ("notion", check_notion),
        ("merge", check_merge),
        ("install", check_install),
    ]
    results = []
    in_repo = None
    for cid, fn in plan:
        if cid in skip:
            results.append((cid, SKIP, "skipped by --skip"))
            continue
        if cid in ("git-locks", "git-fresh", "git-clean") and in_repo is False:
            results.append((cid, SKIP, "not a git repo"))
            continue
        status, message = fn()
        if cid == "git-repo":
            in_repo = status == PASS
        results.append((cid, status, message))
    return results


def exit_code(results):
    return 1 if any(status == FAIL for _cid, status, _m in results) else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Local preflight for the eds-skills pipeline (EDS-11).")
    ap.add_argument("--no-fetch", action="store_true", help="skip `git fetch origin`")
    ap.add_argument("--repo", help="owner/name for the GitHub checks (default: origin remote)")
    ap.add_argument("--skip", default="", help="comma-separated check ids to skip: " + ", ".join(CHECK_IDS))
    args = ap.parse_args(argv)
    skip = [s.strip() for s in args.skip.split(",") if s.strip()]
    unknown = [s for s in skip if s not in CHECK_IDS]
    if unknown:
        ap.error(f"unknown check id(s): {', '.join(unknown)}")

    results = run_checks(repo=args.repo, fetch=not args.no_fetch, skip=skip)
    for cid, status, message in results:
        print(redact(f"[{status}] {cid}: {message}"))
    counts = {s: sum(1 for _c, st, _m in results if st == s) for s in (PASS, FAIL, WARN, SKIP, INFO)}
    print(redact("Summary: " + ", ".join(f"{n} {s}" for s, n in counts.items())))
    code = exit_code(results)
    print("Preflight FAILED." if code else "Preflight OK.")
    return code


if __name__ == "__main__":
    sys.exit(main())
