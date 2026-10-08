#!/usr/bin/env python3
"""
skills/skill-create/main.py

Meta-skill: scaffolds a new skill folder under /skills/ that already
conforms to SKILL_FRAMEWORK.md -- correct structure, required metadata
fields present, naming convention enforced, the correct logic file for
the declared stack (or none, for an instruction-only skill), a generated
SKILL.md (content depth matched to the skill's category), a SECURITY.md
stating the skill's trust boundary (minimal template by default), and a
test.py stub pre-filled with the declared inputs/outputs.

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

# ---------- scaffold placeholder markers (EDS-17) ----------
#
# Text the scaffold writes that a finished skill must no longer contain.
# build_* below and the audit's leftover-marker check both read these, so the
# two cannot drift apart. The audit only scans the *audited* skill's own
# generated files, so these strings appearing here (skill-create's template
# source) never flag skill-create itself.

README_INVOKE_MARKER = "TODO: describe how this skill is invoked."
SKILL_MD_INVOKE_MARKER = "**When to invoke:** TODO -- short trigger description."
SKILL_MD_SYSTEM_MARKERS = [
    "TODO: describe the trigger phrasing for this system skill",
    "TODO: this is a system skill -- SKILL.md's body IS its logic.",
]
SECURITY_MD_MARKER = "TODO: if this skill actually crosses a trust boundary"
TEST_PY_MARKER = "scaffold-level only -- add real assertions"
# Logic file: the scaffold's NotImplementedError and its "TODO: implement" line
# (Python docstring / non-Python stub comment). {skill_name} is substituted.
LOGIC_NOT_IMPLEMENTED_TEMPLATE = "{skill_name}: main.py is a scaffold -- fill in the real logic."
LOGIC_TODO_IMPLEMENT_TEMPLATE = "TODO: implement {skill_name}'s actual logic."

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


if LOG_BACKEND != "cloudwatch":
    os.makedirs("logs", exist_ok=True)
handler = logging.StreamHandler() if LOG_BACKEND == "cloudwatch" else logging.FileHandler("logs/{skill_name}.log")
handler.setFormatter(JsonFormatter())

logger = logging.getLogger("{skill_name}")
logger.setLevel(LOG_LEVEL)
if not logger.handlers:
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


def build_security_md(meta):
    """Every skill gets a SECURITY.md stating its trust boundary explicitly,
    per SKILL_FRAMEWORK.md's Physical Structure. skill-create always scaffolds
    the minimal "no trust boundary" template -- whether a skill actually
    crosses one (shared-config mutation, critical-path execution, network
    ports, shell execution, another tool's data) is a judgment call made
    conversationally when the skill is built, same as SKILL.md's "When to
    invoke" and README's "How to invoke it" TODOs. The scaffold leaves an
    explicit TODO so it's never silently left at the minimal template when
    a real trust boundary exists.
    """
    return (
        "# Security\n\n"
        "**Trust boundary:** None -- this skill reads its declared inputs and writes only its "
        "own generated output files. It does not mutate shared config, execute arbitrary code, "
        "open network ports, or cross any other trust boundary.\n\n"
        f"{SECURITY_MD_MARKER} (shared-config mutation, "
        "critical-path execution, network ports, shell execution, handling another tool's data), "
        "replace the line above and fill in the fuller shape from SKILL_FRAMEWORK.md's "
        "`SECURITY.md` section: What this skill touches / Why that's safe / Out of scope.\n"
    )


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
    lines.append(README_INVOKE_MARKER)
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
    file_list.append("`SECURITY.md` | This skill's trust boundary -- see SKILL_FRAMEWORK.md's SECURITY.md section")
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


FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


NEEDS_PYYAML = "install PyYAML (python3 -m pip install -r requirements.txt) to parse this form"

# Characters PyYAML's reader accepts. Anything else (control characters) is an
# error in YAML; \x85,   and   are accepted but are YAML line breaks,
# which the single-line fallback does not model, so they are excluded too.
_YAML_SAFE_CHARS_RE = re.compile("^[\t\n -~ -‧‪-퟿-�\U00010000-\U0010ffff]*$")

_PLAIN_FIRST_INDICATORS = set("-?:,[]{}#&*!|>'\"%@`")

# YAML 1.1 implicit resolvers (copied from PyYAML's resolver.py): a plain scalar
# matching any of these is NOT a string to yaml.safe_load, so the fallback must
# not return it as one.
_YAML_NON_STRING_PLAIN_RE = re.compile(
    r"^(?:"
    r"yes|Yes|YES|no|No|NO|true|True|TRUE|false|False|FALSE|on|On|ON|off|Off|OFF"
    r"|[-+]?(?:[0-9][0-9_]*)\.[0-9_]*(?:[eE][-+][0-9]+)?"
    r"|\.[0-9][0-9_]*(?:[eE][-+][0-9]+)?"
    r"|[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+\.[0-9_]*"
    r"|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN)"
    r"|[-+]?0b[0-1_]+|[-+]?0[0-7_]+|[-+]?(?:0|[1-9][0-9_]*)|[-+]?0x[0-9a-fA-F_]+"
    r"|[-+]?[1-9][0-9_]*(?::[0-5]?[0-9])+"
    r"|<<|~|null|Null|NULL|="
    r"|[0-9]{4}-[0-9]{2}-[0-9]{2}"
    r"|[0-9]{4}-[0-9]{1,2}-[0-9]{1,2}(?:[Tt]|[ \t]+)[0-9]{1,2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]*)?(?:[ \t]*(?:Z|[-+][0-9]{1,2}(?::[0-9]{2})?))?"
    r")$"
)
_FRONTMATTER_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
_SINGLE_QUOTED_RE = re.compile(r"^'((?:[^']|'')*)'$")
_SURROGATE_ESCAPE_RE = re.compile(r"\\u[dD][89a-fA-F][0-9a-fA-F]{2}")


def _parse_scalar_without_yaml(key, value):
    """Decode one single-line scalar, or raise ValueError saying why this
    fallback cannot. Accepts only forms where yaml.safe_load returns the
    identical str: plain, single-quoted, JSON-style double-quoted."""
    if not value:
        raise ValueError(
            f"{key!r} has an empty value, or a value on following lines "
            f"(multi-line, nested or null): {NEEDS_PYYAML}")
    first = value[0]
    if first == '"':
        if _SURROGATE_ESCAPE_RE.search(value):
            raise ValueError(
                f"{key!r} is a double-quoted scalar with a \\uD800-\\uDFFF surrogate escape, "
                f"which PyYAML decodes differently from JSON: {NEEDS_PYYAML}")
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            raise ValueError(
                f"{key!r} is a double-quoted scalar this fallback cannot decode (it accepts "
                f"JSON-style escapes only, with nothing after the closing quote, e.g. no trailing "
                f"comment): {NEEDS_PYYAML}")
        if not isinstance(decoded, str):
            raise ValueError(f"{key!r} is not a double-quoted string: {NEEDS_PYYAML}")
        return decoded
    if first == "'":
        quoted = _SINGLE_QUOTED_RE.match(value)
        if not quoted:
            raise ValueError(
                f"{key!r} is a single-quoted scalar this fallback cannot decode (a lone quote must "
                f"be doubled, and nothing may follow the closing quote): {NEEDS_PYYAML}")
        return quoted.group(1).replace("''", "'")
    if first in "|>":
        raise ValueError(f"{key!r} is a block (literal or folded) scalar: {NEEDS_PYYAML}")
    if first in "[{":
        raise ValueError(f"{key!r} is a flow collection (list or mapping): {NEEDS_PYYAML}")
    if first in "&*!":
        raise ValueError(f"{key!r} uses a YAML anchor, alias or tag: {NEEDS_PYYAML}")
    if first in _PLAIN_FIRST_INDICATORS:
        raise ValueError(
            f"{key!r} is a plain scalar starting with the YAML indicator {first!r}; quote it, "
            f"or {NEEDS_PYYAML}")
    if "\t" in value:
        raise ValueError(f"{key!r} is a plain scalar containing a tab: {NEEDS_PYYAML}")
    if ": " in value or value.endswith(":"):
        raise ValueError(
            f"{key!r} is a plain scalar containing ': ' (invalid YAML; quote the value)")
    if " #" in value:
        raise ValueError(
            f"{key!r} is a plain scalar containing ' #', which YAML reads as a comment; "
            f"quote the value, or {NEEDS_PYYAML}")
    if _YAML_NON_STRING_PLAIN_RE.match(value):
        raise ValueError(
            f"{key!r} is a plain scalar YAML reads as a number, boolean, null or date, not a "
            f"string; quote it, or {NEEDS_PYYAML}")
    return value


def _parse_frontmatter_without_yaml(block):
    """Stdlib fallback (EDS-39): a mapping of `key: <single-line scalar>` lines,
    a strict subset of YAML (see _parse_scalar_without_yaml). Whatever it
    returns, yaml.safe_load returns too; anything it cannot prove that for
    raises ValueError naming PyYAML as the way to parse it."""
    block = block.replace("\r\n", "\n")
    if not _YAML_SAFE_CHARS_RE.match(block):
        raise ValueError(
            f"frontmatter contains a control character or a YAML line-break character: {NEEDS_PYYAML}")
    data = {}
    for line in block.split("\n"):
        if not line.strip(" "):
            continue
        if line[0] in " \t":
            raise ValueError(
                f"indented frontmatter line {line!r} (continuation or nested value): {NEEDS_PYYAML}")
        if line[0] == "#":
            continue
        key, sep, value = line.partition(":")
        if not sep or not _FRONTMATTER_KEY_RE.match(key) or (value and value[0] != " "):
            raise ValueError(f"unparseable frontmatter line: {line!r}")
        data[key] = _parse_scalar_without_yaml(key, value.strip(" "))
    if not data:
        raise ValueError("frontmatter is not a YAML mapping")
    return data


def parse_frontmatter(text):
    """Parse SKILL.md frontmatter into a dict. Returns None if there is no
    frontmatter block. Raises ValueError if the block is not valid YAML, or (no
    PyYAML) is in a form the stdlib fallback does not parse.

    Uses yaml.safe_load when PyYAML is importable. Otherwise falls back to a
    stdlib parser (EDS-39) of single-line `key: value` lines whose value is a
    plain, single-quoted or JSON-style double-quoted scalar -- the shapes real
    SKILL.md files use, and a strict subset of YAML: it never accepts a value
    that yaml.safe_load would read differently. Block/folded scalars, anchors,
    flow collections, multi-line values and the like are rejected with a
    message saying PyYAML is needed.
    """
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None
    block = match.group(1)
    try:
        import yaml
    except ImportError:
        yaml = None
    if yaml is not None:
        try:
            data = yaml.safe_load(block)
        except yaml.YAMLError as e:
            raise ValueError(f"frontmatter is not valid YAML: {e}")
        if not isinstance(data, dict):
            raise ValueError("frontmatter is not a YAML mapping")
        return data
    return _parse_frontmatter_without_yaml(block)


def build_skill_md(meta):
    # json.dumps output is a valid YAML double-quoted scalar, so ": ", "#",
    # quotes, backslashes and newlines in the description are all safe.
    description = json.dumps(meta["description"])
    frontmatter = f"---\nname: {meta['name']}\ndescription: {description}\n---\n"
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
            f"{SKILL_MD_INVOKE_MARKER}\n\n"
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
        "try:",
        "    import yaml",
        "except ImportError:  # fall back to a strict stdlib check below",
        "    yaml = None",
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
    lines.append("def _parse_frontmatter(block):")
    lines.append("    if yaml is not None:")
    lines.append("        return yaml.safe_load(block)")
    lines.append("    data = {}")
    lines.append('    for line in block.split("\\n"):')
    lines.append('        key, sep, value = line.partition(": ")')
    lines.append('        assert sep, f"unparseable frontmatter line: {line!r}"')
    lines.append('        data[key] = json.loads(value) if key == "description" else value.strip()')
    lines.append("    return data")
    lines.append("")
    lines.append("")
    lines.append("def test_skill_md_has_valid_frontmatter():")
    lines.append('    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")')
    lines.append('    match = re.match(r"^---\\s*\\n(.*?)\\n---\\s*\\n", text, re.DOTALL)')
    lines.append('    assert match, "SKILL.md must start with YAML frontmatter"')
    lines.append("    frontmatter = _parse_frontmatter(match.group(1))")
    lines.append(f'    assert frontmatter["name"] == "{meta["name"]}"')
    lines.append('    assert isinstance(frontmatter["description"], str) and frontmatter["description"].strip(), "SKILL.md needs a non-empty description"')
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
    lines.append(f'    print("All {meta["name"]} contract tests passed ({TEST_PY_MARKER}).")')
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


def _read_text(path):
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else None


def _scaffold_marker_findings(skill_dir, name, meta):
    """Stale findings for placeholder text skill-create itself generated and
    nobody replaced (EDS-17). An untouched scaffold passes test.py, so without
    this the PR gate could not tell it from a finished skill.

    Only the audited skill's own files are read, and only for the exact
    scaffold wording, so skill-create's template source never flags itself
    (its main.py holds "{skill_name}" placeholders, not a concrete name).
    """
    # (file, marker text, what to do)
    checks = [
        ("README.md", README_INVOKE_MARKER, "write the real invocation instructions"),
        ("SKILL.md", SKILL_MD_INVOKE_MARKER, "write the real trigger description"),
        ("SECURITY.md", SECURITY_MD_MARKER,
         "state the skill's real trust boundary and remove the TODO paragraph"),
        ("test.py", TEST_PY_MARKER, "add real assertions and drop the scaffold-level message"),
    ]
    for marker in SKILL_MD_SYSTEM_MARKERS:
        checks.append(("SKILL.md", marker, "write the real content"))

    logic_files = set(STACK_LOGIC_FILE.values())
    if meta is not None and isinstance(meta.get("stack"), list):
        try:
            expected = determine_logic_file(meta["stack"])
        except ScaffoldError:
            expected = None
        if expected:
            logic_files = {expected}
    not_implemented = LOGIC_NOT_IMPLEMENTED_TEMPLATE.format(skill_name=name)
    todo_implement = LOGIC_TODO_IMPLEMENT_TEMPLATE.format(skill_name=name)
    not_implemented_re = re.compile(r"NotImplementedError\(\s*[\"']" + re.escape(not_implemented) + r"[\"']\s*\)")

    findings = []
    for filename, marker, action in checks:
        text = _read_text(skill_dir / filename)
        if text is not None and marker in text:
            findings.append(AuditFinding(
                "stale", f"{filename} still contains the scaffold placeholder \"{marker}\" -- {action}."))
    for filename in sorted(logic_files):
        text = _read_text(skill_dir / filename)
        if text is None:
            continue
        if not_implemented_re.search(text):
            findings.append(AuditFinding(
                "stale",
                f"{filename} still raises the scaffold NotImplementedError "
                f"(\"{not_implemented}\") -- implement the real logic."))
        if todo_implement in text:
            findings.append(AuditFinding(
                "stale",
                f"{filename} still contains the scaffold placeholder \"{todo_implement}\" -- "
                f"implement the real logic and remove it."))
    if not findings:
        findings.append(AuditFinding("ok", "no leftover scaffold placeholders."))
    return findings


FILE_HANDLER_LOGS_RE = re.compile(r"""FileHandler\(\s*f?["']logs/""")
LOGS_DIR_CREATED_RE = re.compile(r"\bmakedirs\(|\.mkdir\(")
ADD_HANDLER_RE = re.compile(r"\.addHandler\(")


def _logging_bootstrap_findings(skill_dir, meta):
    """Findings for the Python logging bootstrap in main.py (EDS-37).

    Stale: a FileHandler("logs/...") with nothing in the file that creates the
    logs directory (os.makedirs / Path.mkdir). That is the pre-EDS-16
    bootstrap, which crashes at import anywhere but a repo root that already
    has logs/. Any makedirs/mkdir call in the file counts as handling it, so
    skills with their own workaround (or skill-create's own _ensure_logs_dir)
    pass.

    Note, not stale: addHandler with no `.handlers` check anywhere in the
    file, which duplicates log lines when the module is imported or reloaded
    twice. A note only, so existing skills keep passing the PR gate.

    Only Python skills (logic file main.py) are inspected.
    """
    if meta is None or not isinstance(meta.get("stack"), list):
        return []
    try:
        expected = determine_logic_file(meta["stack"])
    except ScaffoldError:
        return []
    if expected != "main.py":
        return []
    text = _read_text(skill_dir / expected)
    if text is None:
        return []

    findings = []
    has_file_handler = bool(FILE_HANDLER_LOGS_RE.search(text))
    if has_file_handler and not LOGS_DIR_CREATED_RE.search(text):
        findings.append(AuditFinding(
            "stale",
            "main.py's logging bootstrap opens FileHandler(\"logs/...\") but never creates the "
            "logs directory -- it crashes at import outside a folder that already has logs/. "
            "Add os.makedirs(\"logs\", exist_ok=True) before the handler (see "
            "SKILL_FRAMEWORK.md's Logging Standard)."))
    if ADD_HANDLER_RE.search(text) and ".handlers" not in text:
        findings.append(AuditFinding(
            "note",
            "main.py's logging bootstrap calls addHandler without an `if not logger.handlers` "
            "guard -- importing or reloading it twice in one process duplicates every log line. "
            "Guard it the way skill-create's current bootstrap does."))
    if not any(f.status in ("stale", "note") for f in findings) and has_file_handler:
        findings.append(AuditFinding("ok", "main.py's logging bootstrap creates logs/ and guards addHandler."))
    return findings


def _readme_structure_findings(skill_dir, readme_text):
    """EDS-41: compare the README's Structure table with the files in the
    skill folder. The README is the source for the Notion Skills Library entry
    (DEFINITION_OF_DONE.md), so a file missing from the table silently yields
    an incomplete entry.

    Textual, like the other README checks: reads the first column of the table
    rows under the `## Structure` heading and takes the backticked names (or
    the bare cell text when there are none). Only regular files directly in
    the skill folder count; dotfiles and subfolders (`logs/`, `__pycache__/`)
    are ignored. A file in the folder that the table does not list is stale; a
    listed name with no such file is a note.
    """
    lines = readme_text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip() == "## Structure"), None)
    if start is None:
        return []  # the missing-section finding already covers this
    listed = set()
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        if not line.lstrip().startswith("|"):
            continue
        cells = line.strip().strip("|").split("|")
        first = cells[0].strip()
        if not first or set(first) <= set("-: ") or first.lower() == "file":
            continue
        names = re.findall(r"`([^`]+)`", first)
        listed.update(names if names else [first])
    present = {p.name for p in skill_dir.iterdir() if p.is_file() and not p.name.startswith(".")}
    findings = []
    unlisted = sorted(present - listed)
    if unlisted:
        findings.append(AuditFinding(
            "stale",
            f"README.md's Structure table does not list: {', '.join(unlisted)} -- add a row for "
            f"each file in the skill folder (the Skills Library entry is generated from this table).",
        ))
    else:
        findings.append(AuditFinding("ok", "README.md's Structure table lists every file in the skill folder."))
    missing = sorted(listed - present)
    if missing:
        findings.append(AuditFinding(
            "note",
            f"README.md's Structure table lists {', '.join(missing)}, which is not in the skill "
            f"folder -- remove the row if the file is gone.",
        ))
    return findings


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
        try:
            fm = parse_frontmatter(text)
        except ValueError as e:
            findings.append(AuditFinding("stale", f"SKILL.md frontmatter does not parse: {e}"))
        else:
            if fm is None:
                findings.append(AuditFinding("stale", "SKILL.md doesn't start with valid YAML frontmatter."))
            elif not isinstance(fm.get("description"), str) or not fm["description"].strip():
                findings.append(AuditFinding("stale", "SKILL.md frontmatter has no non-empty string description."))
            else:
                findings.append(AuditFinding("ok", "SKILL.md has valid frontmatter (parsed as YAML)."))
                # SKILL.md's description is the trigger text and legitimately
                # diverges from skill.json's after scaffolding, so a mismatch is
                # a note for a human, not a stale finding.
                if meta is not None and fm["description"] != meta.get("description"):
                    findings.append(AuditFinding(
                        "note",
                        "SKILL.md description differs from skill.json's -- fine if intentional "
                        "(SKILL.md carries the trigger wording), otherwise reconcile them.",
                    ))
        findings.append(AuditFinding(
            "note",
            "SKILL.md content depth can't be checked mechanically -- confirm it still matches "
            "its category's rule (system: full behavioral instructions in the body; "
            "craft/meta: short summary pointing to README.md).",
        ))

    # ---- SECURITY.md ----
    if not (skill_dir / "SECURITY.md").exists():
        findings.append(AuditFinding(
            "stale",
            "SECURITY.md is missing -- required for every skill per SKILL_FRAMEWORK.md's "
            "Physical Structure, even when the honest content is the minimal 'no trust "
            "boundary' template.",
        ))
    else:
        findings.append(AuditFinding("ok", "SECURITY.md present."))
        findings.append(AuditFinding(
            "note",
            "SECURITY.md content accuracy can't be checked mechanically -- confirm it still "
            "reflects this skill's real trust boundary (or honestly states it has none).",
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
        findings.extend(_readme_structure_findings(skill_dir, readme_text))

    if not (skill_dir / "test.py").exists():
        findings.append(AuditFinding("stale", "test.py is missing."))
    else:
        findings.append(AuditFinding("ok", "test.py present."))

    # ---- leftover scaffold placeholders (EDS-17) ----
    findings.extend(_scaffold_marker_findings(skill_dir, name, meta))

    # ---- logging bootstrap content (EDS-37) ----
    findings.extend(_logging_bootstrap_findings(skill_dir, meta))

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
    security_md_content = build_security_md(meta)
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
    (skill_dir / "SECURITY.md").write_text(security_md_content)
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
    print(f"  skill.json, README.md, SECURITY.md, SKILL.md, test.py"
          + (f", {logic_filename}" if logic_filename else " (no logic file -- instruction-only skill)"))
    print("Next: fill in the real logic, real README content, and real test.py assertions,")
    print("then run the Definition of Done sequence before this skill is considered done.")


if __name__ == "__main__":
    main()
