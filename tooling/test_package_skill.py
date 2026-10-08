"""
Contract test for tooling/package_skill.py packaging (EDS-13).

Proves that an installed plugin carries the skill's code, not just SKILL.md:
builds the real .plugin for every skill with build_plugin_zip(), unzips it
into a fresh scratch directory, and asserts every file SKILL.md relies on
(the logic file for the declared stack, README.md, SECURITY.md) is in the
archive and byte-identical (sha256) to skills/<name>/. Does the same for the
plugins/<name>/ directory that regenerate_marketplace() writes.

Run:  python3 tooling/test_package_skill.py
"""

import ast
import contextlib
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import package_skill as ps  # noqa: E402


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def expected_files(name):
    """What an installed plugin must contain next to SKILL.md, derived
    independently of package_skill.py from the skill's own skill.json."""
    skill_dir = ps.SKILLS_DIR / name
    stack = json.loads((skill_dir / "skill.json").read_text())["stack"]
    files = ["SKILL.md", "README.md", "SECURITY.md"]
    if stack == ["Cowork Skill (SKILL.md)"]:
        return files
    logic = {"Python": "main.py", "Node.js": "main.js", "Arduino C++": "sketch.ino"}
    for known, filename in logic.items():
        if known in stack:
            files.append(filename)
            return files
    raise AssertionError(f"{name}: test does not know stack {stack}")


def build_and_extract(name, scratch):
    """Build the .plugin, unzip it into a fresh directory, return
    (archive member names, extraction root)."""
    version = ps.skill_version(name)
    zip_path = ps.build_plugin_zip(name, version, Path(scratch) / "dist")
    extract_root = Path(scratch) / f"unzipped-{name}"
    extract_root.mkdir()
    with zipfile.ZipFile(zip_path) as zf:
        members = sorted(zf.namelist())
        zf.extractall(extract_root)
    return members, extract_root


def test_plugin_zip_contains_skill_logic_and_docs():
    for name in ps.list_skills():
        with tempfile.TemporaryDirectory() as scratch:
            members, root = build_and_extract(name, scratch)
            assert ".claude-plugin/plugin.json" in members, f"{name}: no plugin.json"
            for rel in expected_files(name):
                member = f"skills/{name}/{rel}"
                assert member in members, f"{name}: {member} missing from .plugin; archive has {members}"
                assert sha256(root / member) == sha256(ps.SKILLS_DIR / name / rel), (
                    f"{name}: {member} in .plugin differs from skills/{name}/{rel}"
                )


def test_named_fixtures_ship_their_logic_file():
    # The two cases called out in EDS-13, checked by name so a rename or an
    # empty skills/ directory cannot make the loop above pass vacuously.
    for name, logic in (("pipeline-smoke-test", "main.py"), ("skill-create", "main.py")):
        with tempfile.TemporaryDirectory() as scratch:
            members, _ = build_and_extract(name, scratch)
            assert f"skills/{name}/{logic}" in members, f"{name}: {logic} not in .plugin: {members}"
            assert f"skills/{name}/README.md" in members, f"{name}: README.md not in .plugin: {members}"


def test_regenerated_plugin_dir_matches_zip():
    saved = (ps.PLUGINS_DIR, ps.MARKETPLACE_FILE)
    try:
        with tempfile.TemporaryDirectory() as scratch:
            ps.PLUGINS_DIR = Path(scratch) / "plugins"
            ps.MARKETPLACE_FILE = Path(scratch) / ".claude-plugin" / "marketplace.json"
            ps.regenerate_marketplace()
            for name in ps.list_skills():
                members, root = build_and_extract(name, scratch)
                zip_files = {m: sha256(root / m) for m in members if m.startswith("skills/")}
                plugin_dir = ps.PLUGINS_DIR / name
                dir_files = {
                    p.relative_to(plugin_dir).as_posix(): sha256(p)
                    for p in (plugin_dir / "skills").rglob("*")
                    if p.is_file()
                }
                assert dir_files == zip_files, (
                    f"{name}: plugins/{name}/ and the .plugin differ:\n  dir={dir_files}\n  zip={zip_files}"
                )
                for rel in expected_files(name):
                    assert f"skills/{name}/{rel}" in dir_files, f"{name}: plugins/{name}/ missing {rel}"
    finally:
        ps.PLUGINS_DIR, ps.MARKETPLACE_FILE = saved


def test_stack_table_matches_skill_create():
    # Parse (not import) skill-create's main.py: importing it has side effects.
    tree = ast.parse((ps.SKILLS_DIR / "skill-create" / "main.py").read_text())
    table = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "STACK_LOGIC_FILE" for t in node.targets
        ):
            table = ast.literal_eval(node.value)
    assert table is not None, "STACK_LOGIC_FILE not found in skill-create main.py"
    assert table == ps.STACK_LOGIC_FILE, f"stack tables drifted: {table} vs {ps.STACK_LOGIC_FILE}"


def test_unknown_stack_fails_loudly():
    try:
        ps.logic_file_for("x", {"stack": ["COBOL"]})
    except SystemExit:
        return
    raise AssertionError("an unknown stack must not be packaged silently without its logic file")


SCAFFOLD_META = {
    "name": "widget-maker",
    "version": "1.0.0",
    "category": "craft",
    "layer": "Business Logic",
    "rank": 1,
    "description": "Makes widgets.",
    "inputs": "A widget spec.",
    "outputs": "A widget file. Protocol: direct file output.",
    "dependencies": [],
    "stack": ["Python"],
    "runtime-independent": True,
    "logging": {"level": "info", "format": "json", "backend": "flat-file"},
}


def run_check_on(skills_dir, name):
    """Run cmd_check() for one changed skill that lives in skills_dir (a
    scratch copy, never the real skills/ folder). Git is stubbed out: the
    skill counts as new, so only its test.py and the audit decide the result.
    Returns (exit code or 0, captured stdout)."""
    def no_base_version(skill, ref=None):
        if ref is not None:
            raise subprocess.CalledProcessError(1, "git show")
        return json.loads((Path(skills_dir) / skill / "skill.json").read_text())["version"]

    saved = (ps.SKILLS_DIR, ps.changed_skills, ps.skill_version)
    ps.SKILLS_DIR = Path(skills_dir)
    ps.changed_skills = lambda base: [name]
    ps.skill_version = no_base_version
    out = io.StringIO()
    code = 0
    try:
        with contextlib.redirect_stdout(out):
            try:
                ps.cmd_check("main")
            except SystemExit as e:
                code = e.code
    finally:
        ps.SKILLS_DIR, ps.changed_skills, ps.skill_version = saved
    return code, out.getvalue()


def test_check_fails_an_untouched_scaffold():
    # EDS-36: an untouched scaffold passes its own test.py, so before the audit
    # ran inside check it passed the PR gate.
    with tempfile.TemporaryDirectory() as scratch:
        skills = Path(scratch) / "skills"
        skills.mkdir()
        proc = subprocess.run(
            [sys.executable, str(ps.SKILLS_DIR / "skill-create" / "main.py"),
             "--metadata", json.dumps(SCAFFOLD_META), "--output-dir", str(skills)],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0, f"scaffolding failed: {proc.stdout}{proc.stderr}"
        code, out = run_check_on(skills, "widget-maker")
        assert code == 1, f"check must fail an untouched scaffold, got exit {code}:\n{out}"
        assert "scaffold placeholder" in out, f"expected stale scaffold findings in output:\n{out}"
        assert "skill-create --audit reported stale findings" in out, out


def test_check_passes_a_finished_skill():
    # A finished skill (a copy of the real pipeline-smoke-test) still passes;
    # its audit may carry manual-review notes, which must not fail the gate.
    with tempfile.TemporaryDirectory() as scratch:
        skills = Path(scratch) / "skills"
        skills.mkdir()
        shutil.copytree(ps.SKILLS_DIR / "pipeline-smoke-test", skills / "pipeline-smoke-test",
                        ignore=shutil.ignore_patterns("__pycache__"))
        code, out = run_check_on(skills, "pipeline-smoke-test")
        assert code == 0, f"check must pass a finished skill, got exit {code}:\n{out}"
        assert "0 stale" in out, f"expected the audit to run and report 0 stale:\n{out}"


def _pr(number, ref, repo="o/r"):
    return {"number": number, "head": {"ref": ref, "repo": {"full_name": repo}}}


def run_open_marketplace_pr(open_prs, new_number=30, fail=()):
    """Drive open_marketplace_pr() with git and the GitHub API stubbed.
    Returns the list of (method, path, data) API calls it made. `fail` is a
    set of (method, path-substring) pairs that return HTTP 500."""
    calls = []

    def fake_api(method, path, token, data=None):
        calls.append((method, path, data))
        if any(m == method and s in path for m, s in fail):
            return 500, {}
        if method == "POST" and path == "/repos/o/r/pulls":
            return 201, {"number": new_number, "html_url": "http://x/pr"}
        if method == "GET":
            return 200, open_prs
        return (204 if method == "DELETE" else 200), {}

    class R:
        stdout = " M plugins/x\n"

    saved = (ps.github_api, ps.run)
    ps.github_api = fake_api
    ps.run = lambda cmd, **kw: R()
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            ps.open_marketplace_pr("o/r", "tok")
    finally:
        ps.github_api, ps.run = saved
    return calls


def test_new_sync_pr_closes_only_older_bot_sync_prs():
    prs = [
        _pr(30, "bot/sync-marketplace-new"),                      # the new PR itself
        _pr(25, "bot/sync-marketplace-aaa1111"),                  # older sync: close
        _pr(27, "bot/sync-marketplace-bbb2222"),                  # older sync: close
        _pr(28, "feature/EDS-1-thing"),                           # human PR: keep
        _pr(26, "bot/other-thing"),                               # other bot branch: keep
        _pr(29, "bot/sync-marketplace-fork", repo="evil/r"),      # fork: keep
        _pr(31, "bot/sync-marketplace-newer"),                    # newer than ours: keep
    ]
    calls = run_open_marketplace_pr(prs)
    closed = [p for m, p, d in calls if m == "PATCH"]
    deleted = [p for m, p, d in calls if m == "DELETE"]
    commented = [(p, d) for m, p, d in calls if m == "POST" and p.endswith("/comments")]
    assert closed == ["/repos/o/r/pulls/25", "/repos/o/r/pulls/27"], closed
    assert deleted == [
        "/repos/o/r/git/refs/heads/bot/sync-marketplace-aaa1111",
        "/repos/o/r/git/refs/heads/bot/sync-marketplace-bbb2222",
    ], deleted
    assert [p for p, _ in commented] == [
        "/repos/o/r/issues/25/comments", "/repos/o/r/issues/27/comments"], commented
    assert all("#30" in d["body"] for _, d in commented), commented
    # the close must come after the new PR exists
    order = [(m, p) for m, p, d in calls]
    assert order.index(("POST", "/repos/o/r/pulls")) < order.index(("PATCH", "/repos/o/r/pulls/25"))


def test_close_failure_does_not_fail_release_or_delete_branch():
    prs = [_pr(25, "bot/sync-marketplace-aaa1111")]
    calls = run_open_marketplace_pr(prs, fail={("PATCH", "/pulls/25")})
    assert not [c for c in calls if c[0] == "DELETE"], "must keep the branch if close failed"


def test_sync_pr_body_no_longer_claims_only_skill_json_and_skill_md():
    calls = run_open_marketplace_pr([])
    body = next(d["body"] for m, p, d in calls if m == "POST" and p == "/repos/o/r/pulls")
    assert "fully derived from skills/*/skill.json" not in body, body
    assert "README.md" in body and "closed automatically" in body, body


if __name__ == "__main__":
    test_new_sync_pr_closes_only_older_bot_sync_prs()
    test_close_failure_does_not_fail_release_or_delete_branch()
    test_sync_pr_body_no_longer_claims_only_skill_json_and_skill_md()
    test_check_fails_an_untouched_scaffold()
    test_check_passes_a_finished_skill()
    test_plugin_zip_contains_skill_logic_and_docs()
    test_named_fixtures_ship_their_logic_file()
    test_regenerated_plugin_dir_matches_zip()
    test_stack_table_matches_skill_create()
    test_unknown_stack_fails_loudly()
    print("All package_skill packaging tests passed.")
