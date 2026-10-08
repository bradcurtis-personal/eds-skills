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
import hashlib
import json
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


if __name__ == "__main__":
    test_plugin_zip_contains_skill_logic_and_docs()
    test_named_fixtures_ship_their_logic_file()
    test_regenerated_plugin_dir_matches_zip()
    test_stack_table_matches_skill_create()
    test_unknown_stack_fails_loudly()
    print("All package_skill packaging tests passed.")
