# pipeline-smoke-test

**Category:** Craft skill · **Rank:** 0 · **Layer:** Infrastructure

## What it does

Test fixture for the eds-skills pipeline that prints a greeting with a UTC timestamp and does nothing else.

## How to invoke it

**This is a test fixture with no trust boundary.** It exists only to exercise the eds-skills pipeline (scaffold, PR check, release, marketplace sync, Cowork install, Notion entry) and is not meant for real use.

From the repo root:

```
python3 skills/pipeline-smoke-test/main.py
```

In Cowork, ask to run the pipeline smoke test.

## What it produces

One line on stdout, protocol: direct text output, schema: 'Hello from pipeline-smoke-test at <ISO-8601 UTC timestamp>'.

## Structure

| File | Purpose |
|---|---|
| `skill.json` | Metadata |
| `main.py` | This skill's logic |
| `README.md` | This file |
| `SECURITY.md` | This skill's trust boundary -- see SKILL_FRAMEWORK.md's SECURITY.md section |
| `test.py` | Contract test -- checks metadata, SKILL.md frontmatter, and that `main.py` prints the declared greeting line |
| `SKILL.md` | Cowork-invocable packaging of this skill |

## Version history

- **1.0.1** (EDS-33) — Re-released so the `.plugin` ships `main.py`, `README.md` and `SECURITY.md` alongside `SKILL.md`. Corrected the `SKILL.md` sentence that said an installed plugin ships only that file, and aligned `main.py`'s logging bootstrap with skill-create's current output (handler guard, `logs/` created only for the flat-file backend). No change to the greeting.
- **1.0.0** (EDS-12) — Initial build, as the fixture for the end-to-end pipeline test run.
