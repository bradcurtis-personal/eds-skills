#!/usr/bin/env python3
"""
skills/skill-create/main.py

Meta-skill: scaffolds a new skill folder under /skills/ that already
conforms to SKILL_FRAMEWORK.md -- correct structure, required metadata
fields present, naming convention enforced, the correct logic file for
the declared stack (or none, for an instruction-only skill), a generated
SKILL.md (content depth matched to the skill's category), and a test.py
stub pre-filled with the declared inputs/outputs.

This script does the deterministic scaffolding. Gathering the metadata
from the user is Cowork's job, per SKILL.md's instructions -- by the time
this script runs, every required field should already be known.

Usage:
  python3 skills/skill-create/main.py --metadata '{"name": "arduino-sketch", ...}'
  python3 skills/skill-create/main.py --metadata-file path/to/metadata.json

Optional:
  --output-dir <path>   Write into this directory instead of the real
                         /skills/ library. Used by test.py so the contract
                         test never touches the real skill library.

Required metadata fields, per SKILL_FRAMEWORK.md's Skill Metadata table:
  name, version, category, layer, rank, description, inputs, outputs,
  dependencies, stack, runtime-independent, logging

See SKILL_FRAMEWORK.md's "Logic file naming by stack" section for the
stack -> logic file lookup table below -- add a row there (and here)
whenever a new stack needs to be scaffolded, rather than guessing a
filename inline.
"""
import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = REPO_ROOT / "skills"

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_BACKEND = os.getenv("LOG_BACKEND", "flat-file")


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "level": record.levelname,
            "skill": "skill-create",
            "message": record.getMessage(),
            "timestamp": self.formatTime(record),
        })


def _make_logger():
    handler = (
        logging.StreamHandler()
        if LOG_BACKEND == "cloudwatch"
        else logging.FileHandler("logs/skill-create.log")
        if Path("logs").exists() or _ensure_logs_dir()
        else logging.StreamHandler()
    )
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("skill-create")
    logger.setLevel(LOG_LEVEL)
    if not logger.handlers:
        logger.addHandler(handler)
    return logger


def _ensure_logs_dir():
    Path("logs").mkdir(exist_ok=True)
    return True


logger = _make_logger()

# ---------- naming convention ----------

NAME_PATTERN = re.compile(r"^[a-z]+(-[a-z]+)+$")

# ---------- required metadata (SKILL_FRAMEWORK.md: Skill Metadata) ----------

REQUIRED_FIELDS = [
    "name", "version", "category", "layer", "rank", "description",
    "inputs", "outputs", "dependencies", "stack",
    "runtime-independent", "logging",
]

VALID_CATEGORIES = {"craft", "meta", "system"}
VALID_LAYERS = {"Design", "Presentation", "Business Logic", "Data", "Infrastructure", "Hardware", None}

# ---------- logic file naming by stack (SKILL_FRAMEWORK.md) ----------

STACK_LOGIC_FILE = {
    "Python": "main.py",
    "Node.js": "main.js",
    "Arduino C++": "sketch.ino",
}
INSTRUCTION_ONLY_STACK = "Cowork Skill (SKILL.md)"

PYTHON_LOGGING_BOOTSTRAP = '''import logging
import json
import os

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_BACKEND = os.getenv("LOG_BACKEND", "flat-file")


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({{
            "level": record.levelname,
            "skill": "{skill_name}",
            "message": record.getMessage(),
            "timestamp": self.formatTime(record)
        }})


handler = logging.StreamHandler() if LOG_BACKEND == "cloudwatch" else logging.FileHandler("logs/{skill_name}.log")
handler.setFormatter(JsonFormatter())

logger = logging.getLogger("{skill_name}")
logger.setLevel(LOG_LEVEL)
logger.addHandler(handler)


def main():
    """TODO: implement {skill_name}'s actual logic."""
    logger.info("{skill_name} starting")
    raise NotImplementedError("{skill_name}: main.py is a scaffold -- fill in the real logic.")


if __name__ == "__main__":
    main()
'''

NON_PYTHON_STUB = """// TODO: logging bootstrap not yet defined for {stack} -- see SKILL_FRAMEWORK.md
// TODO: implement {skill_name}'s actual logic.
"""

# ---------- logging bootstrap templates by stack ----------
#
# A stack only belongs here once its logging convention has actually been
# defined (library/module, format, output destination) and documented in
# SKILL_FRAMEWORK.md's Logging Standard -- not just assumed. Scaffolding a
# skill on a stack that isn't in this dict is refused by default (see
# LoggingBootstrapUndefinedError below): the missing convention should be
# resolved conversationally -- ask what this stack's logging should look
# like, add the answer here and to SKILL_FRAMEWORK.md in the same PR -- not
# silently stubbed. --allow-missing-logging-bootstrap is the deliberate,
# explicit escape hatch for when that conversation needs to be deferred.
STACK_LOGGING_BOOTSTRAP = {
    "Python": PYTHON_LOGGING_BOOTSTRAP,
}


class ScaffoldError(Exception):
    pass


class LoggingBootstrapUndefinedError(ScaffoldError):
    """Raised when a stack needs a logic file but has no defined logging
    bootstrap yet, and the caller didn't explicitly opt to defer with
    --allow-missing-logging-bootstrap."""
    pass


def validate_metadata(meta):
    missing = [f for f in REQUIRED_FIELDS if f not in meta]
    if missing:
        raise ScaffoldError(f"Missing required metadata field(s): {', '.join(missing)}")

    if not NAME_PATTERN.match(meta["name"]):
        raise ScaffoldError(
            f"Skill name '{meta['name']}' doesn't match the naming convention "
            f"in SKILL_FRAMEWORK.md: lowercase, hyphenated, [domain]-[action] "
            f"(e.g. 'arduino-sketch', 'skill-create')."
        )

    if meta["category"] not in VALID_CATEGORIES:
        raise ScaffoldError(f"category must be one of {sorted(VALID_CATEGORIES)}, got '{meta['category']}'")

    if meta["category"] == "meta" and meta["layer"] != "Design":
        raise ScaffoldError("Meta-skills must always be assigned the Design layer per SKILL_FRAMEWORK.md.")

    if meta["category"] == "system" and meta["layer"] is not None:
        raise ScaffoldError("System skills are not assigned a layer -- set layer to null.")

    if meta["layer"] not in VALID_LAYERS:
        raise ScaffoldError(f"layer must be one of {sorted(l for l in VALID_LAYERS if l)} or null, got '{meta['layer']}'")

    if not isinstance(meta["rank"], int) or not (0 <= meta["rank"] <= 4):
        raise ScaffoldError(f"rank must be an integer 0-4 per AUTONOMY_RANKS.md, got '{meta['rank']}'")

    if not isinstance(meta["runtime-independent"], bool):
        raise ScaffoldError("runtime-independent must be a boolean")

    if not isinstance(meta["stack"], list) or not meta["stack"]:
        raise ScaffoldError("stack must be a non-empty list")


def _match_known_stack(stack):
    """Returns the matched key from STACK_LOGIC_FILE, or None for an
    instruction-only skill.

    Raises ScaffoldError for a stack this table doesn't know yet, per
    SKILL_FRAMEWORK.md: 'add a row here whenever skill-create needs to
    scaffold one it hasn't seen before, rather than guessing a filename
    inline.'
    """
    if stack == [INSTRUCTION_ONLY_STACK]:
        return None

    for known_stack in STACK_LOGIC_FILE:
        if known_stack in stack:
            return known_stack

    raise ScaffoldError(
        f"Don't know the logic file convention for stack {stack}. "
        f"Add a row to STACK_LOGIC_FILE in this script and to "
        f"SKILL_FRAMEWORK.md's 'Logic file naming by stack' table before "
        f"scaffolding this skill."
    )


def determine_logic_file(stack):
    """Returns the logic file name, or None for an instruction-only skill.
    Raises ScaffoldError for an unrecognized stack -- see _match_known_stack.
    """
    known_stack = _match_known_stack(stack)
    if known_stack is None:
        return None
    return STACK_LOGIC_FILE[known_stack]


def build_skill_json(meta):
    ordered = {field: meta[field] for field in REQUIRED_FIELDS}
    # carry through any extra fields the caller supplied (e.g. rationale fields)
    for k, v in meta.items():
        if k not in ordered:
            ordered[k] = v
    return json.dumps(ordered, indent=2) + "\n"


def build_logic_file(meta, logic_filename, allow_missing_logging_bootstrap=False):
    if logic_filename is None:
        return None

    known_stack = _match_known_stack(meta["stack"])
    if known_stack in STACK_LOGGING_BOOTSTRAP:
        return STACK_LOGGING_BOOTSTRAP[known_stack].format(skill_name=meta["name"])

    if not allow_missing_logging_bootstrap:
        raise LoggingBootstrapUndefinedError(
            f"No logging bootstrap is defined yet for stack '{known_stack}'. Resolve this "
            f"conversationally first -- ask what logging convention this stack should use "
            f"(library/module, format, output destination) -- then add a template to "
            f"STACK_LOGGING_BOOTSTRAP in this script and document the convention in "
            f"SKILL_FRAMEWORK.md's Logging Standard, in the same change. To scaffold with a "
            f"TODO stub instead of resolving this now, pass --allow-missing-logging-bootstrap."
        )

    return NON_PYTHON_STUB.format(stack=", ".join(meta["stack"]), skill_name=meta["name"])


def build_readme(meta, logic_filename):
    lines = [f"# {meta['name']}", ""]
    layer_str = meta["layer"] or "none (system skills aren't layer-assigned)"
    lines.append(f"**Category:** {meta['category'].capitalize()} skill · **Rank:** {meta['rank']} · **Layer:** {layer_str}")
    lines.append("")
    lines.append("## What it does")
    lines.append("")
    lines.append(meta["description"])
    lines.append("")
    lines.append("## How to invoke it")
    lines.append("")
    lines.append("TODO: describe how this skill is invoked.")
    lines.append("")
    lines.append("## What it produces")
    lines.append("")
    lines.append(meta["outputs"])
    lines.append("")
    lines.append("## Structure")
    lines.append("")
    file_list = ["`skill.json` | Metadata"]
    if logic_filename:
        file_list.append(f"`{logic_filename}` | This skill's logic")
    file_list.append("`README.md` | This file")
    file_list.append("`test.py` | Acceptance/contract test")
    file_list.append("`SKILL.md` | Cowork-invocable packaging of this skill")
    lines.append("| File | Purpose |")
    lines.append("|---|---|")
    for entry in file_list:
        lines.append(f"| {entry} |")
    lines.append("")
    if meta["dependencies"]:
        lines.append("## Dependencies")
        lines.append("")
        for dep in meta["dependencies"]:
            lines.append(f"- {dep}")
        lines.append("")
    lines.append("## Version history")
    lines.append("")
    lines.append(f"- **{meta['version']}** — Initial build.")
    lines.append("")
    return "\n".join(lines)


def build_skill_md(meta):
    frontmatter = f"---\nname: {meta['name']}\ndescription: {meta['description']}\n---\n"
    if meta["category"] == "system":
        body = (
            f"\n# {meta['name']}\n\n"
            f"## When to invoke\n\nTODO: describe the trigger phrasing for this system skill "
            f"(see teach-user's SKILL.md for the pattern).\n\n"
            f"## Behavior while active\n\nTODO: this is a system skill -- SKILL.md's body IS its "
            f"logic. Write the full behavioral instruction set here.\n"
        )
    else:
        body = (
            f"\n# {meta['name']}\n\n"
            f"{meta['description']}\n\n"
            f"**When to invoke:** TODO -- short trigger description.\n\n"
            f"**What it produces:** {meta['outputs']}\n\n"
            f"See `README.md` for full detail on how this skill works and what it depends on.\n"
        )
    return frontmatter + body


def build_test_py(meta, logic_filename):
    lines = [
        '"""',
        f"Contract test for the {meta['name']} skill.",
        "",
        "Generated by skill-create as a starting scaffold -- fill in real",
        "assertions against this skill's declared inputs/outputs before",
        "considering it done, per DEFINITION_OF_DONE.md step 2.",
        '"""',
        "",
        "import json",
        "import re",
        "from pathlib import Path",
        "",
        'SKILL_DIR = Path(__file__).parent',
        "REQUIRED_METADATA_FIELDS = [",
    ]
    for f in REQUIRED_FIELDS:
        lines.append(f'    "{f}",')
    lines.append("]")
    lines.append("")
    lines.append("")
    lines.append("def test_skill_json_valid_and_complete():")
    lines.append('    data = json.loads((SKILL_DIR / "skill.json").read_text())')
    lines.append("    for field in REQUIRED_METADATA_FIELDS:")
    lines.append('        assert field in data, f"skill.json missing required field: {field}"')
    lines.append(f'    assert data["name"] == "{meta["name"]}"')
    lines.append(f'    assert data["category"] == "{meta["category"]}"')
    lines.append("")
    lines.append("")
    lines.append("def test_skill_md_has_valid_frontmatter():")
    lines.append('    text = (SKILL_DIR / "SKILL.md").read_text()')
    lines.append('    match = re.match(r"^---\\s*\\n(.*?)\\n---\\s*\\n", text, re.DOTALL)')
    lines.append('    assert match, "SKILL.md must start with YAML frontmatter"')
    lines.append("    frontmatter = match.group(1)")
    lines.append(f'    assert "name: {meta["name"]}" in frontmatter')
    lines.append('    assert "description:" in frontmatter')
    lines.append("")
    if logic_filename:
        lines.append("")
        lines.append(f"def test_logic_file_exists():")
        lines.append(f'    assert (SKILL_DIR / "{logic_filename}").exists(), "expected logic file {logic_filename} is missing"')
        lines.append("")
    lines.append("")
    lines.append('if __name__ == "__main__":')
    lines.append("    test_skill_json_valid_and_complete()")
    lines.append("    test_skill_md_has_valid_frontmatter()")
    if logic_filename:
        lines.append("    test_logic_file_exists()")
    lines.append(f'    print("All {meta["name"]} contract tests passed (scaffold-level only -- add real assertions).")')
    lines.append("")
    return "\n".join(lines)


class AuditFinding:
    """One line of an audit report.

    status is one of "stale", "ok", "note" -- "stale" is something concretely
    wrong per SKILL_FRAMEWORK.md, "note" is something that needs a human/
    Claude to eyeball (can't be asserted mechanically), "ok" is a passed check.
    """

    def __init__(self, status, message):
        self.status = status
        self.message = message

    def __repr__(self):
        return f"[{self.status}] {self.message}"


def audit(name, skills_dir):
    """Read-only audit of an existing skill against current SKILL_FRAMEWORK.md
    rules. Never writes anything -- update mode is audit + report only per
    Brad's decision; a human or Claude fixes flagged files conversationally,
    one file at a time.

    Returns a list of AuditFinding. Raises ScaffoldError if the skill folder
    doesn't exist at all (nothing to audit).
    """
    skill_dir = skills_dir / name
    if not skill_dir.exists():
        raise ScaffoldError(f"{skill_dir} does not exist -- nothing to audit. Use create mode to scaffold it first.")

    findings = []

    # ---- skill.json ----
    skill_json_path = skill_dir / "skill.json"
    meta = None
    if not skill_json_path.exists():
        findings.append(AuditFinding("stale", "skill.json is missing entirely."))
    else:
        try:
            meta = json.loads(skill_json_path.read_text())
        except json.JSONDecodeError as e:
            findings.append(AuditFinding("stale", f"skill.json is not valid JSON: {e}"))

        if meta is not None:
            try:
                validate_metadata(meta)
                findings.append(AuditFinding("ok", "skill.json has all required fields and passes validation."))
            except ScaffoldError as e:
                findings.append(AuditFinding("stale", f"skill.json fails current validation: {e}"))

    # ---- logic file matches declared stack ----
    if meta is not None and "stack" in meta:
        try:
            expected_logic_file = determine_logic_file(meta["stack"])
        except ScaffoldError as e:
            expected_logic_file = None
            findings.append(AuditFinding("stale", f"stack lookup failed: {e}"))
        else:
            all_known_logic_files = set(STACK_LOGIC_FILE.values())
            present_logic_files = [f for f in all_known_logic_files if (skill_dir / f).exists()]

            if expected_logic_file is None:
                if present_logic_files:
                    findings.append(AuditFinding(
                        "stale",
                        f"stack is instruction-only but {', '.join(present_logic_files)} still present -- "
                        f"should be removed or the stack should be corrected.",
                    ))
                else:
                    findings.append(AuditFinding("ok", "instruction-only skill, correctly has no logic file."))
            else:
                if not (skill_dir / expected_logic_file).exists():
                    findings.append(AuditFinding(
                        "stale",
                        f"stack '{meta['stack']}' expects '{expected_logic_file}' but it's missing.",
                    ))
                else:
                    findings.append(AuditFinding("ok", f"logic file '{expected_logic_file}' matches declared stack."))

                extra = [f for f in present_logic_files if f != expected_logic_file]
                if extra:
                    findings.append(AuditFinding(
                        "stale",
                        f"unexpected extra logic file(s) present: {', '.join(extra)} -- "
                        f"stack says the logic file should be '{expected_logic_file}'.",
                    ))

                # non-Python stub still carrying the TODO after a real bootstrap
                # may since have been defined for this stack (ties to task #12).
                if expected_logic_file != "main.py" and (skill_dir / expected_logic_file).exists():
                    text = (skill_dir / expected_logic_file).read_text()
                    if "TODO: logging bootstrap not yet defined" in text:
                        findings.append(AuditFinding(
                            "note",
                            f"'{expected_logic_file}' still has the logging-bootstrap TODO stub -- "
                            f"check whether a real bootstrap has since been defined for this stack "
                            f"in SKILL_FRAMEWORK.md and, if so, fill it in.",
                        ))

    # ---- SKILL.md ----
    skill_md_path = skill_dir / "SKILL.md"
    if not skill_md_path.exists():
        findings.append(AuditFinding("stale", "SKILL.md is missing entirely -- required for every Cowork skill."))
    else:
        text = skill_md_path.read_text()
        if not re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL):
            findings.append(AuditFinding("stale", "SKILL.md doesn't start with valid YAML frontmatter."))
        else:
            findings.append(AuditFinding("ok", "SKILL.md has valid frontmatter."))
        findings.append(AuditFinding(
            "note",
            "SKILL.md content depth can't be checked mechanically -- confirm it still matches "
            "its category's rule (system: full behavioral instructions in the body; "
            "craft/meta: short summary pointing to README.md).",
        ))

    # ---- README.md / test.py presence ----
    README_REQUIRED_SECTIONS = [
        "## What it does", "## How to invoke it", "## What it produces",
        "## Structure", "## Version history",
    ]
    if not (skill_dir / "README.md").exists():
        findings.append(AuditFinding("stale", "README.md is missing."))
    else:
        readme_text = (skill_dir / "README.md").read_text()
        missing_sections = [s for s in README_REQUIRED_SECTIONS if s not in readme_text]
        if missing_sections:
            findings.append(AuditFinding(
                "stale",
                f"README.md is missing required section(s) per SKILL_FRAMEWORK.md's fixed "
                f"order: {', '.join(s.lstrip('# ') for s in missing_sections)}.",
            ))
        else:
            findings.append(AuditFinding("ok", "README.md present with all required sections."))

    if not (skill_dir / "test.py").exists():
        findings.append(AuditFinding("stale", "test.py is missing."))
    else:
        findings.append(AuditFinding("ok", "test.py present."))

    return findings


def scaffold(meta, output_dir, allow_missing_logging_bootstrap=False):
    validate_metadata(meta)
    logic_filename = determine_logic_file(meta["stack"])

    # Build every file's content before touching disk, so a
    # LoggingBootstrapUndefinedError (or any other failure) leaves nothing
    # partially written -- the skill folder either comes into existence
    # complete, or not at all.
    logic_content = build_logic_file(meta, logic_filename, allow_missing_logging_bootstrap) if logic_filename else None
    skill_json_content = build_skill_json(meta)
    readme_content = build_readme(meta, logic_filename)
    skill_md_content = build_skill_md(meta)
    test_py_content = build_test_py(meta, logic_filename)

    skill_dir = output_dir / meta["name"]
    if skill_dir.exists():
        raise ScaffoldError(f"{skill_dir} already exists -- skill-create does not overwrite an existing skill.")
    skill_dir.mkdir(parents=True)

    (skill_dir / "skill.json").write_text(skill_json_content)
    if logic_filename:
        (skill_dir / logic_filename).write_text(logic_content)
    (skill_dir / "README.md").write_text(readme_content)
    (skill_dir / "SKILL.md").write_text(skill_md_content)
    (skill_dir / "test.py").write_text(test_py_content)

    logger.info(f"scaffolded {meta['name']} at {skill_dir}")
    return skill_dir, logic_filename


def main():
    parser = argparse.ArgumentParser(
        description="Scaffold a new skill, or audit an existing one, per SKILL_FRAMEWORK.md."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--metadata", help="Skill metadata as a JSON string. Create mode.")
    group.add_argument("--metadata-file", help="Path to a JSON file containing skill metadata. Create mode.")
    group.add_argument(
        "--audit",
        metavar="SKILL_NAME",
        help="Audit an existing skill against current SKILL_FRAMEWORK.md rules and report "
             "what's stale. Read-only -- never rewrites files. Update mode.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(SKILLS_DIR),
        help="Directory to scaffold into or audit within (default: the real /skills/ library). "
             "test.py overrides this with a temp directory.",
    )
    parser.add_argument(
        "--allow-missing-logging-bootstrap",
        action="store_true",
        help="Create mode only. By default, scaffolding a skill on a stack with no defined "
             "logging bootstrap is refused -- resolve the convention conversationally, add it "
             "to STACK_LOGGING_BOOTSTRAP and to SKILL_FRAMEWORK.md's Logging Standard, then "
             "retry. Pass this flag to explicitly defer that and scaffold with a TODO stub "
             "instead.",
    )
    args = parser.parse_args()

    if args.audit:
        try:
            findings = audit(args.audit, Path(args.output_dir))
        except ScaffoldError as e:
            print(f"skill-create audit failed: {e}", file=sys.stderr)
            sys.exit(1)

        stale = [f for f in findings if f.status == "stale"]
        notes = [f for f in findings if f.status == "note"]
        ok = [f for f in findings if f.status == "ok"]

        print(f"Audit of '{args.audit}':")
        for f in findings:
            print(f"  {f}")
        print()
        print(f"{len(ok)} ok, {len(stale)} stale, {len(notes)} need manual review.")
        if stale:
            print("Nothing was changed -- skill-create's update mode is audit + report only.")
            print("Fix each stale item conversationally, one file at a time, then re-run --audit to confirm.")
            sys.exit(1)
        return

    if args.metadata:
        meta = json.loads(args.metadata)
    else:
        meta = json.loads(Path(args.metadata_file).read_text())

    try:
        skill_dir, logic_filename = scaffold(
            meta, Path(args.output_dir), allow_missing_logging_bootstrap=args.allow_missing_logging_bootstrap
        )
    except LoggingBootstrapUndefinedError as e:
        print(f"skill-create needs a decision before it can scaffold this: {e}", file=sys.stderr)
        sys.exit(2)
    except ScaffoldError as e:
        print(f"skill-create failed: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Scaffolded '{meta['name']}' at {skill_dir}")
    print(f"  skill.json, README.md, SKILL.md, test.py"
          + (f", {logic_filename}" if logic_filename else " (no logic file -- instruction-only skill)"))
    print("Next: fill in the real logic, real README content, and real test.py assertions,")
    print("then run the Definition of Done sequence before this skill is considered done.")


if __name__ == "__main__":
    main()
