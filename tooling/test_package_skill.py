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


if __name__ == "__main__":
    test_check_fails_an_untouched_scaffold()
    test_check_passes_a_finished_skill()
    test_plugin_zip_contains_skill_logic_and_docs()
    test_named_fixtures_ship_their_logic_file()
    test_regenerated_plugin_dir_matches_zip()
    test_stack_table_matches_skill_create()
    test_unknown_stack_fails_loudly()
    print("All package_skill packaging tests passed.")
