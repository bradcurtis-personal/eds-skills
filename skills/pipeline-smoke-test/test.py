"""
Contract test for the pipeline-smoke-test skill.

Checks metadata, SKILL.md frontmatter, and that main.py prints the
declared greeting line.
"""

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL_DIR = Path(__file__).parent
REQUIRED_METADATA_FIELDS = [
    "name",
    "version",
    "category",
    "layer",
    "rank",
    "description",
    "inputs",
    "outputs",
    "dependencies",
    "stack",
    "runtime-independent",
    "logging",
]


def test_skill_json_valid_and_complete():
    data = json.loads((SKILL_DIR / "skill.json").read_text())
    for field in REQUIRED_METADATA_FIELDS:
        assert field in data, f"skill.json missing required field: {field}"
    assert data["name"] == "pipeline-smoke-test"
    assert data["category"] == "craft"


def test_skill_md_has_valid_frontmatter():
    text = (SKILL_DIR / "SKILL.md").read_text()
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    assert match, "SKILL.md must start with YAML frontmatter"
    frontmatter = match.group(1)
    assert "name: pipeline-smoke-test" in frontmatter
    assert "description:" in frontmatter


def test_logic_file_exists():
    assert (SKILL_DIR / "main.py").exists(), "expected logic file main.py is missing"


def test_main_prints_greeting():
    # Run from an empty directory, the way CI sees a fresh checkout (no logs/).
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run(
            [sys.executable, str(SKILL_DIR / "main.py")],
            cwd=tmp, capture_output=True, text=True,
        )
    assert result.returncode == 0, result.stderr
    assert re.fullmatch(
        r"Hello from pipeline-smoke-test at \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\n",
        result.stdout,
    ), f"unexpected output: {result.stdout!r}"


if __name__ == "__main__":
    test_skill_json_valid_and_complete()
    test_skill_md_has_valid_frontmatter()
    test_logic_file_exists()
    test_main_prints_greeting()
    print("All pipeline-smoke-test contract tests passed.")
