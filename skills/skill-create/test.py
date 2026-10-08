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


def test_audit_flags_file_missing_from_readme_structure_table():
    # EDS-41: the README's Structure table feeds the Notion entry, so a file in
    # the folder that the table omits must fail the audit, naming the file.
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        skill_dir, _ = main.scaffold(_base_meta(name="short-table"), out)
        _finish_scaffold(skill_dir)
        readme_path = skill_dir / "README.md"
        original = readme_path.read_text(encoding="utf-8")
        row = next(l for l in original.splitlines() if l.startswith("| `SECURITY.md`"))
        readme_path.write_text(original.replace(row + "\n", ""), encoding="utf-8")

        stale = [f.message for f in main.audit("short-table", out) if f.status == "stale"]
        assert any("SECURITY.md" in m and "Structure table" in m for m in stale), \
            f"expected a stale finding naming SECURITY.md: {stale}"

        readme_path.write_text(original, encoding="utf-8")
        assert not [f for f in main.audit("short-table", out) if f.status == "stale"]


def test_audit_notes_structure_row_for_file_that_does_not_exist():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        skill_dir, _ = main.scaffold(_base_meta(name="ghost-row"), out)
        _finish_scaffold(skill_dir)
        readme_path = skill_dir / "README.md"
        text = readme_path.read_text(encoding="utf-8")
        readme_path.write_text(
            text.replace("| `test.py` |", "| `ghost.py` | Not a real file |\n| `test.py` |"), encoding="utf-8")

        findings = main.audit("ghost-row", out)
        assert not [f for f in findings if f.status == "stale"], findings
        assert any(f.status == "note" and "ghost.py" in f.message for f in findings), findings


def test_audit_ignores_subfolders_and_dotfiles_in_structure_check():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        skill_dir, _ = main.scaffold(_base_meta(name="extra-dirs"), out)
        _finish_scaffold(skill_dir)
        (skill_dir / "logs").mkdir()
        (skill_dir / "logs" / "run.log").write_text("x", encoding="utf-8")
        (skill_dir / ".gitkeep").write_text("", encoding="utf-8")
        assert not [f for f in main.audit("extra-dirs", out) if f.status == "stale"]


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


def test_scaffolded_bootstrap_adds_one_handler_when_imported_twice():
    # EDS-37: the generated bootstrap called logger.addHandler unconditionally,
    # so importing or reloading a scaffolded main.py twice in one process
    # duplicated every log line. Runs in a subprocess from an empty cwd.
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as empty_cwd:
        skill_dir, _ = main.scaffold(_base_meta(name="twice-probe"), Path(tmp))
        probe = (
            "import importlib.util, logging, sys\n"
            "path = sys.argv[1]\n"
            "for i in range(2):\n"
            "    spec = importlib.util.spec_from_file_location('twice_probe_main', path)\n"
            "    spec.loader.exec_module(importlib.util.module_from_spec(spec))\n"
            "print(len(logging.getLogger('twice-probe').handlers))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe, str(skill_dir / "main.py")],
            cwd=empty_cwd, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "1", \
            f"expected exactly one handler after two imports, got {result.stdout.strip()!r}"


def _audit_cli(out, name):
    return subprocess.run(
        [sys.executable, str(MAIN_PATH), "--audit", name, "--output-dir", str(out)],
        capture_output=True, text=True, cwd=str(out),
    )


def test_audit_flags_old_bootstrap_without_makedirs_and_passes_fresh_one():
    # EDS-37: skills scaffolded before the EDS-16 fix keep a bootstrap that
    # opens FileHandler("logs/...") without creating logs/, and --audit used
    # to report them clean.
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        main.scaffold(_base_meta(name="fresh-boot"), out)
        _finish_scaffold(out / "fresh-boot")
        fresh = _audit_cli(out, "fresh-boot")
        assert fresh.returncode == 0, fresh.stdout + fresh.stderr
        assert "0 stale" in fresh.stdout, fresh.stdout
        assert "[note] main.py's logging bootstrap" not in fresh.stdout, fresh.stdout

        main.scaffold(_base_meta(name="old-boot"), out)
        _finish_scaffold(out / "old-boot")
        logic = out / "old-boot" / "main.py"
        text = logic.read_text(encoding="utf-8")
        old_text = text.replace('    os.makedirs("logs", exist_ok=True)\n', "    pass\n")
        assert old_text != text, "template no longer contains the makedirs line this test strips"
        assert "makedirs" not in old_text
        logic.write_text(old_text, encoding="utf-8")
        old = _audit_cli(out, "old-boot")
        assert old.returncode != 0, old.stdout + old.stderr
        stale = [l for l in old.stdout.splitlines() if l.strip().startswith("[stale]")]
        assert len(stale) == 1 and "logging bootstrap" in stale[0] and "logs directory" in stale[0], old.stdout


def test_audit_unguarded_add_handler_is_a_note_not_stale():
    # EDS-37: existing skills may lack the handler guard; the PR gate fails on
    # stale, so this is reported for manual review only.
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        main.scaffold(_base_meta(name="no-guard"), out)
        _finish_scaffold(out / "no-guard")
        logic = out / "no-guard" / "main.py"
        text = logic.read_text(encoding="utf-8")
        unguarded = text.replace("if not logger.handlers:\n    logger.addHandler(handler)",
                                 "logger.addHandler(handler)")
        assert unguarded != text
        logic.write_text(unguarded, encoding="utf-8")
        findings = main.audit("no-guard", out)
        assert not [f for f in findings if f.status == "stale"], findings
        assert any(f.status == "note" and "addHandler" in f.message for f in findings), findings


# ---------- EDS-39: the stdlib frontmatter fallback (no PyYAML) ----------

# Runs main.py with `import yaml` made to fail, exactly as in a venv that has
# no PyYAML, so the fallback is exercised even where this test run has PyYAML.
_NO_YAML_RUNNER = (
    "import runpy, sys\n"
    "sys.modules['yaml'] = None\n"
    "sys.argv = sys.argv[1:]\n"
    "runpy.run_path(sys.argv[0], run_name='__main__')\n"
)

_NO_YAML_PARSER = (
    "import importlib.util, json, sys\n"
    "sys.modules['yaml'] = None\n"
    "spec = importlib.util.spec_from_file_location('sc_main', sys.argv[1])\n"
    "m = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(m)\n"
    "out = []\n"
    "for text in json.loads(sys.stdin.read()):\n"
    "    try:\n"
    "        out.append({'ok': m.parse_frontmatter(text)})\n"
    "    except ValueError as e:\n"
    "        out.append({'error': str(e)})\n"
    "print(json.dumps(out))\n"
)


def _audit_cli_without_yaml(skills_dir, name):
    with tempfile.TemporaryDirectory() as cwd:
        return subprocess.run(
            [sys.executable, "-c", _NO_YAML_RUNNER, str(MAIN_PATH),
             "--audit", name, "--output-dir", str(skills_dir)],
            capture_output=True, text=True, cwd=cwd,
        )


# (raw `description:` value, the str the fallback and yaml.safe_load must both return)
ACCEPTED_DESCRIPTIONS = [
    ("Prints a greeting.", "Prints a greeting."),
    ("padded   ", "padded"),
    ('Says "hi," then \u2014 leaves. Not [a list] or {a map}, it\'s fine', 'Says "hi," then \u2014 leaves. Not [a list] or {a map}, it\'s fine'),
    ("Reads http://x.y/z and a:b", "Reads http://x.y/z and a:b"),
    ("C# and F# tools", "C# and F# tools"),
    ("3D models for printing", "3D models for printing"),
    ("Yes and no questions", "Yes and no questions"),
    ("Null pointer guide", "Null pointer guide"),
    ("1.2.3", "1.2.3"),
    ("Zus\u00e4tzlich \u2014 na\u00efve, start-stop.", "Zus\u00e4tzlich \u2014 na\u00efve, start-stop."),
    ("'Says hi.'", "Says hi."),
    ("'It''s a skill: really # yes'", "It's a skill: really # yes"),
    ("'Path C:\\x \\n \"q\"'", 'Path C:\\x \\n "q"'),
    ('"Says hi."', "Says hi."),
    ('"Line\\nbreak \\"q\\" \\\\ \\u00fc: # x"', 'Line\nbreak "q" \\ \u00fc: # x'),
    ('"padded"   ', "padded"),
    (json.dumps('Says "hi": it\'s a # comment, C:\\path\nsecond line, \u00fcn\u00efcode'),
     'Says "hi": it\'s a # comment, C:\\path\nsecond line, \u00fcn\u00efcode'),
]

# (raw `description:` value, text the failure message must contain,
#  whether yaml.safe_load must also fail: True where the value is simply invalid YAML)
REJECTED_DESCRIPTIONS = [
    ("", "empty value", False),
    ("|\n  literal\n  block", "block", False),
    (">-\n  folded\n  block", "block", False),
    ("folded text\n  continues here", "PyYAML", False),
    ("[a, b]", "flow collection", False),
    ("{a: b}", "flow collection", False),
    ("&anchor value", "anchor, alias or tag", False),
    ("*alias", "anchor, alias or tag", False),
    ("!!str 5", "anchor, alias or tag", False),
    ("%percent", "indicator", False),
    ("@at", "indicator", False),
    ("`tick", "indicator", False),
    ("- item", "indicator", False),
    ("? key", "indicator", False),
    ("# just a comment", "indicator", False),
    ("has a: colon", "invalid YAML", True),
    ("trailing colon:", "invalid YAML", True),
    ("text # trailing comment", "comment", False),
    ("123", "number, boolean, null or date", False),
    ("1.5", "number, boolean, null or date", False),
    ("true", "number, boolean, null or date", False),
    ("Off", "number, boolean, null or date", False),
    ("null", "number, boolean, null or date", False),
    ("~", "number, boolean, null or date", False),
    ("2026-10-08", "number, boolean, null or date", False),
    ("tab\there", "tab", True),
    ('"x" # trailing comment', "cannot decode", False),
    ('"a\\x41"', "cannot decode", False),
    ('"\\e"', "cannot decode", False),
    ('"\\ud83d\\ude00"', "surrogate", False),
    ('"unterminated', "cannot decode", True),
    ("'unterminated", "cannot decode", True),
    ("'it's'", "cannot decode", True),
    ("'x' # trailing comment", "cannot decode", False),
    ("line\u2028break", "line-break character", True),
    ("bell\x07char", "control character", True),
]


def _frontmatter_text(raw_description):
    return f"---\nname: demo-skill\ndescription: {raw_description}\n---\n\nbody\n"


def _fallback_results(texts):
    probe = subprocess.run(
        [sys.executable, "-c", _NO_YAML_PARSER, str(MAIN_PATH)],
        input=json.dumps(texts), capture_output=True, text=True,
    )
    assert probe.returncode == 0, probe.stderr
    return json.loads(probe.stdout)


def _real_yaml():
    try:
        import yaml
        return yaml
    except ImportError:
        return None


def test_fallback_frontmatter_accepts_plain_single_and_double_quoted_scalars():
    # EDS-39: without PyYAML the fallback accepted only a double-quoted
    # description, so the repo's own plain-description SKILL.md files failed.
    # Every accepted value must be exactly what yaml.safe_load returns.
    yaml = _real_yaml()
    results = _fallback_results([_frontmatter_text(raw) for raw, _ in ACCEPTED_DESCRIPTIONS])
    for (raw, expected), result in zip(ACCEPTED_DESCRIPTIONS, results):
        assert "ok" in result, f"fallback rejected {raw!r}: {result}"
        assert result["ok"] == {"name": "demo-skill", "description": expected}, (raw, result)
        if yaml is not None:
            assert yaml.safe_load(_frontmatter_text(raw).split("---\n")[1]) == result["ok"], raw
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        for i, (raw, _) in enumerate(ACCEPTED_DESCRIPTIONS):
            name = f"accept-{'abcdefghijklmnopqrstuvwxyz'[i]}"
            skill_dir, _ = main.scaffold(_base_meta(name=name), out)
            _finish_scaffold(skill_dir)
            (skill_dir / "SKILL.md").write_text(
                _frontmatter_text(raw).replace("demo-skill", name), encoding="utf-8")
            audit = _audit_cli_without_yaml(out, name)
            assert audit.returncode == 0, f"{raw!r}:\n{audit.stdout}{audit.stderr}"
            assert "0 stale" in audit.stdout, audit.stdout


def test_fallback_frontmatter_rejects_other_forms_with_a_clear_message():
    yaml = _real_yaml()
    results = _fallback_results([_frontmatter_text(raw) for raw, _, _ in REJECTED_DESCRIPTIONS])
    for (raw, message, invalid_yaml), result in zip(REJECTED_DESCRIPTIONS, results):
        assert "error" in result, f"fallback accepted {raw!r}: {result}"
        assert message in result["error"], (raw, result)
        if message != "invalid YAML":
            assert "PyYAML" in result["error"], (raw, result)
        if invalid_yaml and yaml is not None:
            try:
                yaml.safe_load(_frontmatter_text(raw).split("---\n")[1])
            except yaml.YAMLError:
                pass
            else:
                raise AssertionError(f"yaml.safe_load unexpectedly accepted {raw!r}")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        for i, (raw, message, _) in enumerate(REJECTED_DESCRIPTIONS):
            name = f"reject-{'abcdefghijklmnopqrstuvwxyz'[i // 26]}{'abcdefghijklmnopqrstuvwxyz'[i % 26]}"
            skill_dir, _ = main.scaffold(_base_meta(name=name), out)
            _finish_scaffold(skill_dir)
            (skill_dir / "SKILL.md").write_text(
                _frontmatter_text(raw).replace("demo-skill", name), encoding="utf-8")
            audit = _audit_cli_without_yaml(out, name)
            assert audit.returncode != 0, f"{raw!r}:\n{audit.stdout}{audit.stderr}"
            assert "SKILL.md frontmatter does not parse" in audit.stdout, audit.stdout
            assert message in audit.stdout, f"{raw!r}: {audit.stdout}"


def test_fallback_frontmatter_rejects_non_mapping_and_malformed_lines():
    results = _fallback_results([
        "---\njust text\n---\n",
        "---\nname:demo-skill\n---\n",
        "---\n# only a comment\n---\n",
        "---\nname: demo-skill\n  description: indented\n---\n",
    ])
    assert all("error" in r for r in results), results


def test_audit_passes_for_every_skill_in_the_library_without_pyyaml():
    # EDS-39: in a venv without PyYAML, `--audit` exited 1 on skill-create's and
    # pipeline-smoke-test's own SKILL.md. Audit every real skill with `import
    # yaml` blocked and require exit 0.
    skills_dir = SKILL_DIR.parent
    names = sorted(p.name for p in skills_dir.iterdir() if (p / "SKILL.md").exists())
    assert {"skill-create", "pipeline-smoke-test", "teach-user"} <= set(names), names
    for name in names:
        audit = _audit_cli_without_yaml(skills_dir, name)
        assert audit.returncode == 0, f"{name}:\n{audit.stdout}{audit.stderr}"
        assert "0 stale" in audit.stdout, audit.stdout


# ---------- EDS-42: non-ASCII descriptions and the generated test.py's fallback ----------

def _generated_test_without_yaml(skill_dir):
    with tempfile.TemporaryDirectory() as cwd:
        return subprocess.run(
            [sys.executable, "-c", _NO_YAML_RUNNER, str(skill_dir / "test.py")],
            capture_output=True, text=True, cwd=cwd, encoding="utf-8",
        )


def _parse_without_yaml(texts):
    return _fallback_results(texts)


NON_ASCII_DESCRIPTIONS = [
    "Says hello \U0001F600 to naïve café users — déjà vu",   # emoji + accents + em dash
    "CJK 日本語 and \U0001F9EA\U0001F680 plane-1 characters",
    "Line separator, next line, NEL\u0085, DEL\x7f, BOM﻿ end",           # chars YAML treats specially
]


def test_generator_writes_non_ascii_descriptions_as_themselves_not_surrogate_pairs():
    # EDS-42: json.dumps' default ensure_ascii wrote an emoji as a 😀
    # pair, which PyYAML and json.loads decode differently.
    yaml = _real_yaml()
    for i, description in enumerate(NON_ASCII_DESCRIPTIONS):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            skill_dir, _ = main.scaffold(_base_meta(name=f"unicode-skill-{'abc'[i]}", description=description), out)
            text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
            assert not main._SURROGATE_ESCAPE_RE.search(text), text
            if "\U0001F600" in description:
                assert "\U0001F600" in text, "emoji should be written as itself"
            if yaml is not None:
                assert _frontmatter_description(skill_dir) == description
            # the stdlib fallback (no PyYAML) must agree
            (result,) = _parse_without_yaml([text])
            assert result.get("ok", {}).get("description") == description, result
            assert main.parse_frontmatter(text)["description"] == description
            _finish_scaffold(skill_dir)
            assert not [f for f in main.audit(f"unicode-skill-{'abc'[i]}", out) if f.status == "stale"]


def test_generated_test_py_has_the_audits_fallback_without_pyyaml():
    # EDS-42: the generated test.py used to carry its own double-quoted-only
    # fallback. It now carries a copy of the audit's, so it accepts the same
    # shapes and rejects the same ones, without PyYAML.
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        skill_dir, _ = main.scaffold(_base_meta(name="gen-fallback", description="Generated skill."), out)
        run = _generated_test_without_yaml(skill_dir)
        assert run.returncode == 0, run.stdout + run.stderr

        for raw in ["Plain description for gen-fallback.", "'Single: quoted # one'", '"Double \\"quoted\\" one"',
                    json.dumps(NON_ASCII_DESCRIPTIONS[0], ensure_ascii=False)]:
            (skill_dir / "SKILL.md").write_text(
                f"---\nname: gen-fallback\ndescription: {raw}\n---\n\nbody\n", encoding="utf-8")
            run = _generated_test_without_yaml(skill_dir)
            assert run.returncode == 0, f"{raw!r}:\n{run.stdout}{run.stderr}"

        for raw, message in [("|\n  block\n  scalar", "PyYAML"), ("has a: colon", "invalid YAML"),
                             ('"\\ud83d\\ude00"', "surrogate")]:
            (skill_dir / "SKILL.md").write_text(
                f"---\nname: gen-fallback\ndescription: {raw}\n---\n\nbody\n", encoding="utf-8")
            run = _generated_test_without_yaml(skill_dir)
            assert run.returncode != 0 and message in run.stderr, f"{raw!r}:\n{run.stdout}{run.stderr}"


def test_generated_test_py_fallback_is_a_copy_of_mains():
    # Built from main.py's live objects, so the two cannot drift.
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        skill_dir, _ = main.scaffold(_base_meta(name="gen-copy"), out)
        generated = (skill_dir / "test.py").read_text(encoding="utf-8")
        import inspect
        for fn in (main._parse_scalar_without_yaml, main._parse_frontmatter_without_yaml):
            assert inspect.getsource(fn).rstrip("\n") in generated, fn.__name__
        for name in ("_YAML_SAFE_CHARS_RE", "_YAML_NON_STRING_PLAIN_RE", "_FRONTMATTER_KEY_RE",
                     "_SINGLE_QUOTED_RE", "_SURROGATE_ESCAPE_RE"):
            assert getattr(main, name).pattern == _compiled_pattern(generated, name), name


def _compiled_pattern(source, name):
    namespace = {"re": __import__("re")}
    line = next(l for l in source.splitlines() if l.startswith(f"{name} = "))
    exec(line, namespace)
    return namespace[name].pattern


def test_audit_reads_and_scaffold_writes_utf8_regardless_of_locale():
    # EDS-42: Path.read_text() with no encoding uses the locale's default
    # (cp1252 on Windows), which mangles or rejects teach-user's em dash.
    # Audit a skill whose files hold non-ASCII text, with UTF-8 mode off and a
    # C locale, and require a clean run.
    import os
    description = NON_ASCII_DESCRIPTIONS[0]
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        skill_dir, _ = main.scaffold(_base_meta(name="locale-skill", description=description), out)
        _finish_scaffold(skill_dir)
        readme = skill_dir / "README.md"
        readme.write_text(readme.read_text(encoding="utf-8") + "\nNon-ASCII — é \U0001F600\n", encoding="utf-8")
        env = dict(os.environ, PYTHONUTF8="0", PYTHONCOERCECLOCALE="0", LC_ALL="C", LANG="C")
        run = subprocess.run(
            [sys.executable, str(MAIN_PATH), "--audit", "locale-skill", "--output-dir", str(out)],
            capture_output=True, text=True, encoding="utf-8", env=env, cwd=tmp,
        )
        assert run.returncode == 0, run.stdout + run.stderr


def _run_all():
    # Run every test_ function in file order, so a new test cannot be written
    # and then left out of a hand-kept list (the EDS-41 tests were).
    tests = sorted((f.__code__.co_firstlineno, n, f) for n, f in globals().items()
                   if n.startswith("test_") and callable(f))
    for _, _, fn in tests:
        fn()
    print("All skill-create contract tests passed.")


if __name__ == "__main__":
    _run_all()
