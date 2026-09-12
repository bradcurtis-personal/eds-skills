# teach-user

**Category:** System skill · **Rank:** 0 · **Layer:** none (system skills aren't layer-assigned)

## What it does

Overrides the default "speed by default" behavior for a single interaction when the user wants something explained or taught rather than just delivered. While active, it slows down, explains the what/why/context behind the work, offers to go deeper, and logs the explanation as a new subpage under the Notion "Learning" index.

## How to invoke it

Ask to have something explained, taught, or walked through. This skill is not invoked by default — normal work proceeds at speed unless this skill is explicitly triggered.

## What it produces

- Explanatory, slower-paced responses for the duration of the invocation.
- One new Notion subpage per explanation, filed under the "Learning" index page, capturing what was explained.

## Structure

This is a pure-instruction system skill — it has no logic file (no `main.py` or equivalent), since its entire behavior is a set of instructions for how the agent should act, not code that runs. See `SKILL_FRAMEWORK.md`'s "Physical Structure" section for why this is a supported, non-exceptional shape for a skill.

| File | Purpose |
|---|---|
| `skill.json` | Metadata |
| `SKILL.md` | Cowork-invocable instructions (this is the skill's actual "logic") |
| `README.md` | This file |
| `test.py` | Structural contract test — validates `SKILL.md` frontmatter and required behaviors are present |

## Dependencies

Requires a Notion "Learning" index page to exist and be shared with the workspace's Notion integration.
