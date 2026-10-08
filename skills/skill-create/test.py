"""
Contract test for the skill-create meta-skill.

Runs main.py's scaffolding and audit logic against a disposable temp
directory -- never the real /skills/ library -- and verifies the output
actually conforms to SKILL_FRAMEWORK.md: required metadata present, naming
convention enforced, the correct logic file chosen per declared stack
(including the instruction-only "no logic file" case and the "unknown
stack fails loudly" case), a valid SKILL.md, scaffolding is blocked by
default on a stack with no defined logging bootstrap (with an explicit
override to defer that), and update mode's audit is read-only and reports
real drift accurately.
"""

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL_DIR = Path(__file__).parent
MAIN_PATH = SKILL_DIR / "main.py"

_spec = importlib.util.spec_from_file_location("skill_create_main", MAIN_PATH)
main = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(main)


def _base_meta(**overrides):
    meta = {
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
    meta.update(overrides)
    return meta


def _finish_scaffold(skill_dir):
    """Replace every placeholder the scaffold wrote, as a human finishing the
    skill would. Uses main's marker constants rather than literals so this
    file never itself contains the scaffold wording."""
    name = skill_dir.name

    def rewrite(filename, fn):
        path = skill_dir / filename
        if path.exists():
            path.write_text(fn(path.read_text(encoding="utf-8")), encoding="utf-8")

    rewrite("README.md", lambda t: t.replace(main.README_INVOKE_MARKER, "Run it from Cowork."))
    def skill_md(t):
        t = t.replace(main.SKILL_MD_INVOKE_MARKER, "**When to invoke:** when asked to make widgets.")
        for m in main.SKILL_MD_SYSTEM_MARKERS:
            t = t.replace(m, "Real instructions.")
        return t
    rewrite("SKILL.md", skill_md)
    rewrite("SECURITY.md", lambda t: "".join(
        line for line in t.splitlines(keepends=True) if not line.startswith(main.SECURITY_MD_MARKER)))
    rewrite("test.py", lambda t: t.replace(main.TEST_PY_MARKER, "real assertions"))
    for logic in main.STACK_LOGIC_FILE.values():
        def logic_fix(t):
            t = t.replace(main.LOGIC_NOT_IMPLEMENTED_TEMPLATE.format(skill_name=name), "implemented")
            return t.replace(main.LOGIC_TODO_IMPLEMENT_TEMPLATE.format(skill_name=name), "Implemented.")
        rewrite(logic, logic_fix)


def test_audit_flags_untouched_scaffold_and_passes_once_filled_in():
    # EDS-17: an untouched scaffold used to audit clean (0 stale), so nothing
    # in the PR gate could tell it from a finished skill. Drives the real CLI.
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        skill_dir, _ = main.scaffold(_base_meta(name="raw-scaffold"), out)

        def run_audit():
            return subprocess.run(
                [sys.executable, str(MAIN_PATH), "--audit", "raw-scaffold", "--output-dir", str(out)],
                capture_output=True, text=True, cwd=tmp,
            )

        raw = run_audit()
        assert raw.returncode != 0, raw.stdout + raw.stderr
        for expected in (
            "README.md still contains the scaffold placeholder",
            "SKILL.md still contains the scaffold placeholder",
            "SECURITY.md still contains the scaffold placeholder",
            "test.py still contains the scaffold placeholder",
            "main.py still raises the scaffold NotImplementedError",
            "main.py still contains the scaffold placeholder",
        ):
            assert expected in raw.stdout, f"missing finding {expected!r}:\n{raw.stdout}"

        _finish_scaffold(skill_dir)
        done = run_audit()
        assert done.returncode == 0, done.stdout + done.stderr
        assert "0 stale" in done.stdout, done.stdout


def test_audit_flags_each_marker_individually_and_for_system_skills():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        main.scaffold(_base_meta(name="sys-scaffold", category="system", layer=None,
                                 stack=["Cowork Skill (SKILL.md)"]), out)
        stale = [f.message for f in main.audit("sys-scaffold", out) if f.status == "stale"]
        assert sum("SKILL.md still contains" in m for m in stale) == 2, stale
        _finish_scaffold(out / "sys-scaffold")
        assert not [f for f in main.audit("sys-scaffold", out) if f.status == "stale"]

        # a single leftover marker is enough to fail
        main.scaffold(_base_meta(name="one-marker"), out)
        _finish_scaffold(out / "one-marker")
        readme = out / "one-marker" / "README.md"
        readme.write_text(readme.read_text(encoding="utf-8") + "\n" + main.README_INVOKE_MARKER + "\n",
                          encoding="utf-8")
        stale = [f.message for f in main.audit("one-marker", out) if f.status == "stale"]
        assert len(stale) == 1 and "README.md" in stale[0], stale


def test_audit_of_skill_create_itself_has_no_marker_findings():
    # skill-create's own main.py/test.py legitimately hold the marker text as
    # template source; auditing skill-create must not mis-flag it.
    findings = main.audit("skill-create", SKILL_DIR.parent)
    assert not [f for f in findings if f.status == "stale"], findings


def test_scaffolds_python_craft_skill():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        skill_dir, logic_filename = main.scaffold(_base_meta(), out)

        assert logic_filename == "main.py"
        assert (skill_dir / "skill.json").exists()
        assert (skill_dir / "main.py").exists()
        assert (skill_dir / "README.md").exists()
        assert (skill_dir / "SECURITY.md").exists()
        assert (skill_dir / "SKILL.md").exists()
        assert (skill_dir / "test.py").exists()

        data = json.loads((skill_dir / "skill.json").read_text())
        for field in main.REQUIRED_FIELDS:
            assert field in data, f"skill.json missing field: {field}"
        assert data["name"] == "widget-maker"

        logic_text = (skill_dir / "main.py").read_text()
        assert "widget-maker" in logic_text
        assert "LOG_BACKEND" in logic_text  # real bootstrap, not a TODO stub

        skill_md = (skill_dir / "SKILL.md").read_text()
        assert skill_md.startswith("---\nname: widget-maker")

        readme_text = (skill_dir / "README.md").read_text()
        for section in ("## What it does", "## How to invoke it", "## What it produces",
                         "## Structure", "## Version history"):
            assert section in readme_text, f"README.md missing required section: {section}"
        assert "1.0.0" in readme_text  # seeded initial version entry

        security_text = (skill_dir / "SECURITY.md").read_text()
        assert security_text.startswith("# Security")
        assert "Trust boundary" in security_text
        assert "TODO" in security_text  # prompts a real trust-boundary review, not silently minimal


def _frontmatter_description(skill_dir):
    """Parse SKILL.md's frontmatter with real YAML, as the ticket requires."""
    import re
    import yaml

    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    assert match, "SKILL.md must start with frontmatter"
    return yaml.safe_load(match.group(1))["description"]


def test_description_with_colon_space_is_valid_yaml_and_round_trips():
    # EDS-15: an unquoted "pipeline: prints" made the frontmatter invalid YAML
    # while the old regex-only checks still reported it valid.
    description = "Test fixture for the eds-skills pipeline: prints a greeting with a UTC timestamp."
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        skill_dir, _ = main.scaffold(_base_meta(name="colon-skill", description=description), out)
        assert _frontmatter_description(skill_dir) == description
        _finish_scaffold(skill_dir)
        findings = main.audit("colon-skill", out)
        assert not any(f.status == "stale" for f in findings), findings


def test_description_with_quotes_hash_backslash_newline_round_trips():
    description = 'Says "hi": it\'s a # comment, C:\\path\nsecond line, ünïcode'
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        skill_dir, _ = main.scaffold(_base_meta(name="tricky-skill", description=description), out)
        assert _frontmatter_description(skill_dir) == description
        assert main.parse_frontmatter((skill_dir / "SKILL.md").read_text(encoding="utf-8"))["description"] == description


def test_audit_flags_unparseable_frontmatter():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        main.scaffold(_base_meta(name="broken-yaml"), out)
        md = out / "broken-yaml" / "SKILL.md"
        md.write_text("---\nname: broken-yaml\ndescription: Has a pipeline: colon\n---\n\nbody\n", encoding="utf-8")
        findings = main.audit("broken-yaml", out)
        assert any(f.status == "stale" and "frontmatter" in f.message for f in findings), findings


def test_generated_test_py_catches_bad_frontmatter():
    description = "Colon: here"
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        skill_dir, _ = main.scaffold(_base_meta(name="gen-test", description=description), out)
        spec = importlib.util.spec_from_file_location("gen_test", skill_dir / "test.py")
        gen = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gen)
        gen.test_skill_md_has_valid_frontmatter()  # passes on good output
        (skill_dir / "SKILL.md").write_text(
            "---\nname: gen-test\ndescription: Colon: here\n---\n", encoding="utf-8")
        rejected = False
        try:
            gen.test_skill_md_has_valid_frontmatter()
        except Exception:
            rejected = True
        assert rejected, "generated test.py must reject invalid YAML frontmatter"


def test_scaffolded_main_runs_from_empty_cwd_without_logs_dir():
    # EDS-16: the generated logging bootstrap used to open logs/<skill>.log at
    # import, so a scaffolded main.py crashed with FileNotFoundError anywhere
    # a logs/ folder did not already exist (fresh checkout, CI, other cwd).
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as empty_cwd:
        skill_dir, _ = main.scaffold(_base_meta(name="cwd-probe"), Path(tmp))
        assert list(Path(empty_cwd).iterdir()) == []
        result = subprocess.run(
            [sys.executable, str(skill_dir / "main.py")],
            cwd=empty_cwd, capture_output=True, text=True,
        )
        assert "FileNotFoundError" not in result.stderr, result.stderr
        # The only acceptable failure for an untouched scaffold is its own stub.
        assert result.returncode != 0 and "NotImplementedError" in result.stderr, result.stderr
        assert (Path(empty_cwd) / "logs" / "cwd-probe.log").exists()


def test_scaffolds_instruction_only_skill_with_no_logic_file():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        meta = _base_meta(
            name="teach-example",
            category="system",
            layer=None,
            stack=["Cowork Skill (SKILL.md)"],
        )
        skill_dir, logic_filename = main.scaffold(meta, out)

        assert logic_filename is None
        assert not (skill_dir / "main.py").exists()
        assert (skill_dir / "skill.json").exists()
        assert (skill_dir / "SKILL.md").exists()


def test_missing_logging_bootstrap_blocks_scaffolding_by_default():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        meta = _base_meta(name="sensor-wiring", stack=["Arduino C++"])
        try:
            main.scaffold(meta, out)
            assert False, "expected LoggingBootstrapUndefinedError for a stack with no defined bootstrap"
        except main.LoggingBootstrapUndefinedError as e:
            assert "Arduino C++" in str(e)
        # and nothing partial should have been written
        assert not (out / "sensor-wiring").exists()


def test_missing_logging_bootstrap_override_produces_todo_stub():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        meta = _base_meta(name="sensor-wiring", stack=["Arduino C++"])
        skill_dir, logic_filename = main.scaffold(meta, out, allow_missing_logging_bootstrap=True)

        assert logic_filename == "sketch.ino"
        stub_text = (skill_dir / "sketch.ino").read_text()
        assert "TODO: logging bootstrap not yet defined for Arduino C++" in stub_text


def test_defined_logging_bootstrap_is_used_without_override():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        meta = _base_meta(name="python-thing", stack=["Python"])
        skill_dir, logic_filename = main.scaffold(meta, out)
        text = (skill_dir / "main.py").read_text()
        assert "TODO: logging bootstrap" not in text
        assert "LOG_BACKEND" in text


def test_unknown_stack_fails_loudly_instead_of_guessing():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        meta = _base_meta(name="rust-thing", stack=["Rust"])
        try:
            main.scaffold(meta, out)
            assert False, "expected ScaffoldError for an unrecognized stack"
        except main.ScaffoldError as e:
            assert "Rust" in str(e)


def test_naming_convention_is_enforced():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        meta = _base_meta(name="BadName")
        try:
            main.scaffold(meta, out)
            assert False, "expected ScaffoldError for a name violating the naming convention"
        except main.ScaffoldError:
            pass


def test_does_not_overwrite_existing_skill():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        meta = _base_meta(name="one-shot")
        main.scaffold(meta, out)
        try:
            main.scaffold(meta, out)
            assert False, "expected ScaffoldError when the skill folder already exists"
        except main.ScaffoldError:
            pass


def test_meta_skill_must_be_design_layer():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        meta = _base_meta(name="bad-meta-skill", category="meta", layer="Data")
        try:
            main.scaffold(meta, out)
            assert False, "expected ScaffoldError: meta-skills must be Design layer"
        except main.ScaffoldError:
            pass


def test_scaffold_always_includes_security_md():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        meta = _base_meta(name="teach-example", category="system", layer=None,
                           stack=["Cowork Skill (SKILL.md)"])
        skill_dir, _ = main.scaffold(meta, out)
        assert (skill_dir / "SECURITY.md").exists(), \
            "SECURITY.md is a fixed required file for every skill, regardless of stack/category"


def test_audit_flags_missing_security_md():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        main.scaffold(_base_meta(name="no-security-doc"), out)
        (out / "no-security-doc" / "SECURITY.md").unlink()

        findings = main.audit("no-security-doc", out)
        stale = [f for f in findings if f.status == "stale"]
        assert any("SECURITY.md" in f.message for f in stale), \
            f"expected a stale finding about the missing SECURITY.md: {findings}"


def test_audit_does_not_flag_present_security_md():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        skill_dir, _ = main.scaffold(_base_meta(name="has-security-doc"), out)
        _finish_scaffold(skill_dir)

        findings = main.audit("has-security-doc", out)
        stale = [f for f in findings if f.status == "stale"]
        assert not any("SECURITY.md" in f.message for f in stale), \
            f"SECURITY.md is present, should not be flagged stale: {findings}"


def test_audit_reports_missing_skill_as_error():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        try:
            main.audit("does-not-exist", out)
            assert False, "expected ScaffoldError when auditing a nonexistent skill"
        except main.ScaffoldError:
            pass


def test_audit_clean_skill_is_all_ok():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        skill_dir, _ = main.scaffold(_base_meta(name="clean-skill"), out)
        _finish_scaffold(skill_dir)
        findings = main.audit("clean-skill", out)
        assert findings, "expected at least one finding"
        assert not any(f.status == "stale" for f in findings), \
            f"scaffolded-then-finished skill should have no stale findings: {findings}"


def test_audit_flags_missing_skill_json_field():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        main.scaffold(_base_meta(name="drifted-skill"), out)
        skill_json_path = out / "drifted-skill" / "skill.json"
        data = json.loads(skill_json_path.read_text())
        del data["rank"]
        skill_json_path.write_text(json.dumps(data))

        findings = main.audit("drifted-skill", out)
        stale = [f for f in findings if f.status == "stale"]
        assert any("rank" in f.message or "skill.json" in f.message for f in stale), \
            f"expected a stale finding about the missing field: {findings}"


def test_audit_flags_readme_missing_required_section():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        main.scaffold(_base_meta(name="thin-readme"), out)
        readme_path = out / "thin-readme" / "README.md"
        text = readme_path.read_text()
        assert "## Version history" in text
        readme_path.write_text(text.split("## Version history")[0])  # lop off the section

        findings = main.audit("thin-readme", out)
        stale = [f for f in findings if f.status == "stale"]
        assert any("Version history" in f.message for f in stale), \
            f"expected a stale finding about the missing README section: {findings}"


def test_audit_flags_extra_logic_file_after_stack_change():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        main.scaffold(_base_meta(name="switched-stack"), out)
        skill_dir = out / "switched-stack"
        skill_json_path = skill_dir / "skill.json"
        data = json.loads(skill_json_path.read_text())
        data["stack"] = ["Cowork Skill (SKILL.md)"]
        skill_json_path.write_text(json.dumps(data))
        # main.py from the old Python stack is still sitting there

        findings = main.audit("switched-stack", out)
        stale = [f for f in findings if f.status == "stale"]
        assert any("main.py" in f.message for f in stale), \
            f"expected a stale finding about the leftover main.py: {findings}"


def test_audit_never_writes_anything():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        main.scaffold(_base_meta(name="untouched-skill"), out)
        skill_dir = out / "untouched-skill"
        before = {p: p.read_bytes() for p in skill_dir.iterdir()}

        main.audit("untouched-skill", out)

        after = {p: p.read_bytes() for p in skill_dir.iterdir()}
        assert before == after, "audit must never modify the audited skill's files"
        assert set(before.keys()) == set(after.keys()), "audit must never add/remove files"


if __name__ == "__main__":
    test_scaffolds_python_craft_skill()
    test_description_with_colon_space_is_valid_yaml_and_round_trips()
    test_description_with_quotes_hash_backslash_newline_round_trips()
    test_audit_flags_unparseable_frontmatter()
    test_generated_test_py_catches_bad_frontmatter()
    test_scaffolded_main_runs_from_empty_cwd_without_logs_dir()
    test_scaffolds_instruction_only_skill_with_no_logic_file()
    test_missing_logging_bootstrap_blocks_scaffolding_by_default()
    test_missing_logging_bootstrap_override_produces_todo_stub()
    test_defined_logging_bootstrap_is_used_without_override()
    test_unknown_stack_fails_loudly_instead_of_guessing()
    test_naming_convention_is_enforced()
    test_does_not_overwrite_existing_skill()
    test_meta_skill_must_be_design_layer()
    test_scaffold_always_includes_security_md()
    test_audit_flags_missing_security_md()
    test_audit_does_not_flag_present_security_md()
    test_audit_reports_missing_skill_as_error()
    test_audit_clean_skill_is_all_ok()
    test_audit_flags_missing_skill_json_field()
    test_audit_flags_readme_missing_required_section()
    test_audit_flags_extra_logic_file_after_stack_change()
    test_audit_never_writes_anything()
    test_audit_flags_untouched_scaffold_and_passes_once_filled_in()
    test_audit_flags_each_marker_individually_and_for_system_skills()
    test_audit_of_skill_create_itself_has_no_marker_findings()
    print("All skill-create contract tests passed.")
