"""
Contract test for the teach-user system skill.

teach-user has no executable logic file -- its "output" is a SKILL.md
instruction set. Its acceptance test therefore validates structure and
required content rather than runtime behavior:
  1. skill.json exists, is valid JSON, and declares the required metadata
     fields from SKILL_FRAMEWORK.md.
  2. SKILL.md exists, has valid YAML frontmatter with name + description.
  3. SKILL.md's body actually contains the behaviors this skill promises:
     the offer to go deeper/move on, the Notion "Learning" logging step,
     the depth-preference question, the mid-explanation opt-out, and
     negative-trigger guidance (EDS-5).
"""

import json
import re
from pathlib import Path

SKILL_DIR = Path(__file__).parent
REQUIRED_METADATA_FIELDS = [
    "name", "version", "category", "layer", "rank", "description",
    "inputs", "outputs", "dependencies", "stack",
    "runtime-independent", "logging",
]


def test_skill_json_valid_and_complete():
    data = json.loads((SKILL_DIR / "skill.json").read_text())
    for field in REQUIRED_METADATA_FIELDS:
        assert field in data, f"skill.json missing required field: {field}"
    assert data["name"] == "teach-user"
    assert data["category"] == "system"
    assert data["layer"] is None
    assert data["rank"] == 0
    assert data["runtime-independent"] is False


def test_skill_md_has_valid_frontmatter():
    text = (SKILL_DIR / "SKILL.md").read_text()
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    assert match, "SKILL.md must start with YAML frontmatter"
    frontmatter = match.group(1)
    assert "name: teach-user" in frontmatter
    assert "description:" in frontmatter


def test_skill_md_declares_required_behaviors():
    text = (SKILL_DIR / "SKILL.md").read_text().lower()
    assert "notion" in text and "learning" in text, \
        "SKILL.md must instruct logging explanations to the Notion Learning index"
    assert "go deeper" in text or "move on" in text, \
        "SKILL.md must instruct offering to go deeper or move on"
    assert "speed-mode" in text or "speed mode" in text, \
        "SKILL.md must reference returning to default speed-mode"


def test_skill_md_declares_eds5_behaviors():
    text = (SKILL_DIR / "SKILL.md").read_text().lower()
    assert "depth" in text, \
        "SKILL.md must let the user set explanation depth (EDS-5)"
    assert "opt-out" in text or "skip the explanation" in text or "skip ahead" in text, \
        "SKILL.md must describe a mid-explanation opt-out (EDS-5)"
    assert "do not invoke" in text, \
        "SKILL.md must include explicit negative-trigger examples (EDS-5)"
    assert "cleaned-up" in text or "cleaned up" in text, \
        "SKILL.md must clarify Notion logs are cleaned-up writeups, not transcripts (EDS-5)"


if __name__ == "__main__":
    test_skill_json_valid_and_complete()
    test_skill_md_has_valid_frontmatter()
    test_skill_md_declares_required_behaviors()
    test_skill_md_declares_eds5_behaviors()
    print("All teach-user contract tests passed.")
