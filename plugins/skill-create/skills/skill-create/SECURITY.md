# Security

**Trust boundary:** None -- this skill reads its declared inputs and writes only its own generated output files (new skill folders under `/skills/<name>/`). It does not mutate shared config, execute arbitrary code, open network ports, or cross any other trust boundary.

**Dependencies:** `main.py` needs only the Python standard library. `test.py` additionally requires PyYAML (`import yaml`), a test-time dependency pinned in the repo's `requirements.txt` and installed by the `skill-pr-check` workflow. `main.py` (generator and `--audit`) and the generated `test.py` use PyYAML to parse `SKILL.md` frontmatter when it is importable and fall back to a strict stdlib check of the double-quoted `description:` shape when it is not. The generator runs without it; an audit without it reports a stale frontmatter for any `SKILL.md` whose description is not double-quoted.

The one action that touches a shared, durable surface -- writing a skill's entry to Notion during the documentation pass -- happens conversationally, outside `main.py`, only after explicit user confirmation of the drafted content (see README.md's "Documentation pass" section). `main.py` itself never reaches outside the local filesystem.
