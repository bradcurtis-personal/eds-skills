"""
Tests for tooling/preflight.py (EDS-11).

Every subprocess call goes through preflight.run(), which these tests replace
with a stub, so nothing here touches the network, gh, or the real checkout
(lock-file detection uses a scratch directory).

Run:  python3 tooling/test_preflight.py
(tooling/test_package_skill.py also runs these, which is how CI covers them.)
"""

import contextlib
from collections import namedtuple
import io
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import preflight as pf  # noqa: E402

TOKEN = "github_pat_11ABCDEFG0123456789_secretsecretsecret"


@contextlib.contextmanager
def stub_run(responses):
    """responses: list of (command prefix tuple, (rc, out, err)); the first
    prefix that matches wins; unmatched commands fail the test."""
    calls = []

    def fake(cmd, cwd=None, timeout=60):
        calls.append(list(cmd))
        for prefix, result in responses:
            if tuple(cmd[:len(prefix)]) == tuple(prefix):
                return result
        raise AssertionError(f"unexpected command: {cmd}")

    saved = pf.run
    pf.run = fake
    try:
        yield calls
    finally:
        pf.run = saved


# --- EDS-14 -----------------------------------------------------------------

def test_python_pass_and_missing_yaml_warns():
    saved = pf.have_module
    try:
        pf.have_module = lambda name: True
        status, msg = pf.check_python()
        assert status == pf.PASS and "PyYAML" in msg and sys.version.split()[0] in msg, (status, msg)
        pf.have_module = lambda name: False
        status, msg = pf.check_python()
        assert status == pf.WARN and "pip install pyyaml" in msg, (status, msg)
    finally:
        pf.have_module = saved


def test_old_python_warns():
    saved = (pf.sys, pf.have_module)

    class FakeSys:
        version_info = namedtuple("V", "major minor micro")(3, 9, 1)
    pf.sys = FakeSys
    pf.have_module = lambda name: True
    try:
        status, msg = pf.check_python()
    finally:
        pf.sys, pf.have_module = saved
    assert status == pf.WARN and "3.10" in msg, (status, msg)


# --- EDS-18 -----------------------------------------------------------------

def test_git_repo_pass_and_fail():
    with stub_run([(("git", "rev-parse", "--is-inside-work-tree"), (0, "true\n", "")),
                   (("git", "rev-parse", "--show-toplevel"), (0, "/x/eds-skills\n", ""))]):
        status, msg = pf.check_git_repo()
        assert status == pf.PASS and "/x/eds-skills" in msg, (status, msg)
    with stub_run([(("git", "rev-parse"), (128, "", "fatal: not a git repository"))]):
        status, msg = pf.check_git_repo()
        assert status == pf.FAIL and "not inside a git repo" in msg, (status, msg)


def test_lock_files_are_found_and_reported():
    with tempfile.TemporaryDirectory() as scratch:
        git = Path(scratch) / ".git"
        (git / "objects").mkdir(parents=True)
        with stub_run([(("git", "rev-parse", "--git-common-dir"), (0, str(git) + "\n", ""))]):
            status, msg = pf.check_git_locks()
            assert status == pf.PASS, (status, msg)
            (git / "objects" / "maintenance.lock").write_bytes(b"")
            status, msg = pf.check_git_locks()
            assert status == pf.WARN and "maintenance.lock" in msg and "did not block" in msg, (status, msg)
            (git / "index.lock").write_text("x")
            status, msg = pf.check_git_locks()
            assert status == pf.WARN and "index.lock" in msg and "can block" in msg, (status, msg)


def fresh_responses(branch, head, tip, mb=None, behind="0", ahead="0", fetch_rc=0):
    r = [
        (("git", "fetch", "origin"), (fetch_rc, "", "fatal: unable to access" if fetch_rc else "")),
        (("git", "rev-parse", "origin/main"), (0, tip + "\n", "")),
        (("git", "rev-parse", "--abbrev-ref", "HEAD"), (0, branch + "\n", "")),
        (("git", "rev-parse", "HEAD"), (0, head + "\n", "")),
        (("git", "rev-list", "--count", "HEAD..origin/main"), (0, behind + "\n", "")),
        (("git", "rev-list", "--count", "origin/main..HEAD"), (0, ahead + "\n", "")),
        (("git", "rev-list", "--count"), (0, behind + "\n", "")),
    ]
    if mb is not None:
        r.append((("git", "merge-base", "HEAD", "origin/main"), (0, mb + "\n", "")))
    else:
        r.append((("git", "merge-base"), (1, "", "")))
    return r


def test_main_equal_to_origin_passes():
    with stub_run(fresh_responses("main", "aaa", "aaa")):
        status, msg = pf.check_git_fresh()
        assert status == pf.PASS and "equal to origin/main" in msg, (status, msg)


def test_main_behind_origin_fails_with_count():
    with stub_run(fresh_responses("main", "aaa", "bbb", behind="3")):
        status, msg = pf.check_git_fresh()
        assert status == pf.FAIL and "behind origin/main by 3" in msg and "origin/main" in msg, (status, msg)
        assert "freshly fetched" in msg, msg


def test_main_ahead_warns():
    with stub_run(fresh_responses("main", "aaa", "bbb", behind="0", ahead="2")):
        status, msg = pf.check_git_fresh()
        assert status == pf.WARN and "2 commit" in msg, (status, msg)


def test_feature_branch_up_to_date_passes():
    with stub_run(fresh_responses("feature/EDS-1-x", "ccc", "bbb", mb="bbb")):
        status, msg = pf.check_git_fresh()
        assert status == pf.PASS and "feature/EDS-1-x" in msg, (status, msg)


def test_feature_branch_behind_fails_with_count():
    with stub_run(fresh_responses("feature/EDS-1-x", "ccc", "bbb", mb="aaa", behind="4")):
        status, msg = pf.check_git_fresh()
        assert status == pf.FAIL and "behind origin/main by 4" in msg, (status, msg)


def test_detached_head_is_judged_like_a_branch():
    with stub_run(fresh_responses("HEAD", "bbb", "bbb", mb="bbb")):
        status, msg = pf.check_git_fresh(fetch=False)
        assert status == pf.PASS and "detached HEAD" in msg, (status, msg)


def test_no_merge_base_warns_for_shallow_clone():
    with stub_run(fresh_responses("feature/x", "ccc", "bbb", mb=None)):
        status, msg = pf.check_git_fresh()
        assert status == pf.WARN and "merge-base" in msg, (status, msg)


def test_no_fetch_skips_the_network_and_says_so():
    with stub_run(fresh_responses("main", "aaa", "aaa")) as calls:
        status, msg = pf.check_git_fresh(fetch=False)
        assert status == pf.PASS and "--no-fetch" in msg, (status, msg)
        assert ["git", "fetch", "origin"] not in calls, calls
    with stub_run(fresh_responses("main", "aaa", "aaa")) as calls:
        pf.check_git_fresh(fetch=True)
        assert ["git", "fetch", "origin"] in calls, calls


def test_fetch_failure_warns_and_missing_origin_main_fails():
    with stub_run(fresh_responses("main", "aaa", "aaa", fetch_rc=1)):
        status, msg = pf.check_git_fresh()
        assert status == pf.WARN and "cannot verify" in msg, (status, msg)
    with stub_run([(("git", "rev-parse", "origin/main"), (128, "", "unknown revision"))]):
        status, msg = pf.check_git_fresh(fetch=False)
        assert status == pf.FAIL and "git fetch origin" in msg, (status, msg)


def test_working_tree_clean_and_dirty():
    with stub_run([(("git", "status", "--porcelain"), (0, "", ""))]):
        assert pf.check_git_clean()[0] == pf.PASS
    with stub_run([(("git", "status", "--porcelain"), (0, " M a.py\n?? b.py\n", ""))]):
        status, msg = pf.check_git_clean()
        assert status == pf.WARN and "2 uncommitted" in msg, (status, msg)


# --- EDS-20 -----------------------------------------------------------------

def test_gh_auth_pass_never_shows_the_token():
    banner = f"github.com\n  Logged in\n  - Token: {TOKEN}\n"
    with stub_run([(("gh", "auth", "status"), (0, banner, ""))]):
        status, msg = pf.check_gh_auth()
    assert status == pf.PASS and TOKEN not in msg and "github_pat_" not in msg, (status, msg)


def test_gh_auth_missing_and_unauthenticated_fail():
    with stub_run([(("gh", "auth", "status"), (127, "", "gh: command not found"))]):
        status, msg = pf.check_gh_auth()
        assert status == pf.FAIL and "not found" in msg, (status, msg)
    with stub_run([(("gh", "auth", "status"), (1, "", f"You are not logged in; {TOKEN}"))]):
        status, msg = pf.check_gh_auth()
        assert status == pf.FAIL and TOKEN not in msg, (status, msg)


PROBE_422 = (1, '{"message":"Validation Failed","errors":[{"resource":"PullRequest","field":"head","code":"invalid"}],'
                '"status":"422"}', "gh: Validation Failed (HTTP 422)")
PROBE_403 = (1, '{"message":"Resource not accessible by personal access token","status":"403"}',
             "gh: Resource not accessible by personal access token (HTTP 403)")


def probe(result):
    with stub_run([(("gh", "api"), result)]) as calls:
        status, msg = pf.check_pr_write("o/r")
    return status, msg, calls


def test_pr_write_422_passes_and_403_fails():
    status, msg, calls = probe(PROBE_422)
    assert status == pf.PASS and "422" in msg, (status, msg)
    # the probe must be the invalid-head create, aimed at the right repo
    cmd = calls[0]
    assert cmd[:2] == ["gh", "api"] and "repos/o/r/pulls" in cmd and "POST" in cmd, cmd
    assert "head=preflight-nonexistent-branch" in cmd, cmd
    status, msg, _ = probe(PROBE_403)
    assert status == pf.FAIL and "403" in msg and "Pull requests" in msg, (status, msg)


def test_pr_write_other_outcomes():
    status, msg, _ = probe((0, '{"number": 99}', ""))
    assert status == pf.FAIL and "UNEXPECTED" in msg and "gh pr list" in msg, (status, msg)
    status, msg, _ = probe((1, "", "gh: Bad credentials (HTTP 401)"))
    assert status == pf.FAIL and "401" in msg, (status, msg)
    status, msg, _ = probe((1, "", "gh: Not Found (HTTP 404)"))
    assert status == pf.FAIL and "404" in msg, (status, msg)
    status, msg, _ = probe((1, "", "error connecting to api.github.com"))
    assert status == pf.WARN and "inconclusive" in msg, (status, msg)
    status, msg, _ = probe((127, "", "gh: command not found"))
    assert status == pf.SKIP, (status, msg)
    assert pf.check_pr_write(None)[0] == pf.SKIP


def test_pr_write_output_never_leaks_a_token():
    status, msg, _ = probe((1, "", f"gh: weird failure with {TOKEN} in it"))
    assert TOKEN not in msg and "github_pat_" not in msg, msg


# --- EDS-40 -----------------------------------------------------------------

def rules_json(*contexts, with_rule=True):
    rules = [{"type": "deletion"}, {"type": "pull_request", "parameters": {}}]
    if with_rule:
        rules.append({"type": "required_status_checks", "parameters": {
            "required_status_checks": [{"context": c, "integration_id": 15368} for c in contexts]}})
    return json.dumps(rules)


def ruleset(result):
    with stub_run([(("gh", "api", "repos/o/r/rules/branches/main"), result)]):
        return pf.check_ruleset("o/r")


def test_ruleset_parsing():
    status, msg = ruleset((0, rules_json("check"), ""))
    assert status == pf.PASS and "'check'" in msg, (status, msg)
    status, msg = ruleset((0, rules_json("check", "lint"), ""))
    assert status == pf.PASS, (status, msg)
    status, msg = ruleset((0, rules_json("lint"), ""))
    assert status == pf.FAIL and "lint" in msg and "EDS-40" in msg, (status, msg)
    status, msg = ruleset((0, rules_json(with_rule=False), ""))
    assert status == pf.FAIL and "none" in msg, (status, msg)
    status, msg = ruleset((0, "[]", ""))
    assert status == pf.FAIL, (status, msg)


def test_ruleset_unreadable_skips():
    status, msg = ruleset((1, "", "gh: Resource not accessible by personal access token (HTTP 403)"))
    assert status == pf.SKIP and "not readable" in msg, (status, msg)
    assert ruleset((0, "<html>", ""))[0] == pf.SKIP
    assert ruleset((0, '{"message": "x"}', ""))[0] == pf.SKIP
    assert pf.check_ruleset(None)[0] == pf.SKIP


# --- EDS-24, 21, 23 ---------------------------------------------------------

def test_manual_checks_explain_themselves():
    status, msg = pf.check_notion()
    assert status == pf.SKIP and "skill.json" in msg and "Version history" in msg, (status, msg)
    assert pf.redact(msg) == msg, "ordinary prose must survive redaction"
    status, msg = pf.check_merge()
    assert status == pf.INFO and "gh pr merge" in msg and "human" in msg, (status, msg)
    status, msg = pf.check_install()
    assert status == pf.INFO and "new session" in msg, (status, msg)


# --- driver -----------------------------------------------------------------

def test_default_repo_parses_remotes_without_leaking_credentials():
    for url, want in (("https://github.com/o/r.git\n", "o/r"),
                      ("git@github.com:o/r.git\n", "o/r"),
                      ("https://x:" + TOKEN + "@github.com/o/r\n", "o/r")):
        with stub_run([(("git", "remote", "get-url", "origin"), (0, url, ""))]):
            assert pf.default_repo() == want, url
    with stub_run([(("git", "remote", "get-url", "origin"), (2, "", "no such remote"))]):
        assert pf.default_repo() is None


def test_redact_removes_tokens():
    for secret in (TOKEN, "ghp_abcdefghijklmnop1234", "Token: abcdef1234567890zz",
                   "https://user:pw@github.com/o/r", "Authorization: Bearer abc.def"):
        out = pf.redact(f"before {secret} after")
        assert "abcdef1234567890zz" not in out and "github_pat_" not in out and "ghp_" not in out, out
        assert "pw@" not in out and "abc.def" not in out, out


def all_green_responses():
    return [
        (("git", "rev-parse", "--is-inside-work-tree"), (0, "true\n", "")),
        (("git", "rev-parse", "--show-toplevel"), (0, "/x\n", "")),
        (("git", "rev-parse", "--git-common-dir"), (0, tempfile.gettempdir() + "/preflight-no-such-git\n", "")),
        (("git", "remote", "get-url", "origin"), (0, "https://github.com/o/r.git\n", "")),
        (("git", "status", "--porcelain"), (0, "", "")),
        (("gh", "auth", "status"), (0, f"Token: {TOKEN}\n", "")),
        (("gh", "api", "repos/o/r/pulls"), PROBE_422),
        (("gh", "api", "repos/o/r/rules/branches/main"), (0, rules_json("check"), "")),
    ] + fresh_responses("main", "aaa", "aaa")


def run_main(argv, responses):
    out = io.StringIO()
    with stub_run(responses) as calls, contextlib.redirect_stdout(out):
        code = pf.main(argv)
    return code, out.getvalue(), calls


def test_exit_code_is_one_only_when_something_fails():
    assert pf.exit_code([("a", pf.PASS, ""), ("b", pf.WARN, ""), ("c", pf.SKIP, ""), ("d", pf.INFO, "")]) == 0
    assert pf.exit_code([("a", pf.PASS, ""), ("b", pf.FAIL, "")]) == 1


def test_main_all_green_exits_zero_and_prints_one_line_per_check():
    code, out, calls = run_main(["--no-fetch"], all_green_responses())
    assert code == 0, out
    lines = [l for l in out.splitlines() if l.startswith("[")]
    assert len(lines) == len(pf.CHECK_IDS), out
    assert all(l.split("]")[0] in ("[PASS", "[WARN", "[SKIP", "[INFO", "[FAIL") for l in lines), out
    assert "Preflight OK." in out and "Summary:" in out, out
    assert ["git", "fetch", "origin"] not in calls, "--no-fetch must not fetch"
    assert TOKEN not in out and "github_pat_" not in out, out


def test_main_exits_one_when_the_probe_is_403_and_never_prints_secrets():
    responses = [(("gh", "api", "repos/o/r/pulls"), (1, TOKEN, "Resource not accessible by personal access token (HTTP 403)"))]
    responses += all_green_responses()
    code, out, _ = run_main(["--no-fetch"], responses)
    assert code == 1 and "[FAIL] pr-write" in out and "Preflight FAILED." in out, out
    assert TOKEN not in out, out


def test_skip_flag_and_repo_flag():
    code, out, calls = run_main(["--no-fetch", "--repo", "x/y", "--skip", "pr-write,ruleset,gh-auth"],
                                all_green_responses())
    assert code == 0 and "[SKIP] pr-write: skipped by --skip" in out, out
    assert not [c for c in calls if c[:2] == ["gh", "api"]], calls
    code, out, calls = run_main(["--no-fetch", "--repo", "x/y", "--skip", "ruleset"],
                                [(("gh", "api", "repos/x/y/pulls"), PROBE_422)] + all_green_responses())
    assert "[PASS] pr-write" in out and ["git", "remote", "get-url", "origin"] not in calls, out
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            pf.main(["--skip", "nonsense"])
    except SystemExit as e:
        assert e.code == 2
    else:
        raise AssertionError("an unknown --skip id must be rejected")


def test_not_a_git_repo_skips_the_other_git_checks():
    responses = [(("git", "rev-parse", "--is-inside-work-tree"), (128, "", "fatal")),
                 (("git", "remote", "get-url", "origin"), (128, "", "fatal"))]
    code, out, _ = run_main(["--no-fetch"], responses + [(("gh", "auth", "status"), (0, "", ""))])
    assert code == 1 and "[FAIL] git-repo" in out, out
    for cid in ("git-locks", "git-fresh", "git-clean"):
        assert f"[SKIP] {cid}: not a git repo" in out, out
    assert "[SKIP] pr-write" in out and "[SKIP] ruleset" in out, out


def test_real_run_helper_handles_missing_commands():
    rc, out, err = pf.run(["definitely-not-a-real-command-xyz"])
    assert rc == 127 and "not found" in err, (rc, out, err)
    rc, _, err = pf.run(["/"])  # not executable: PermissionError, still no raise
    assert rc == 127, (rc, err)


ALL_TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]


def main():
    for test in ALL_TESTS:
        test()
    print("All preflight tests passed.")


if __name__ == "__main__":
    main()
