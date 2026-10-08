# teach-user

**Category:** System skill · **Rank:** 0 · **Layer:** none (system skills aren't layer-assigned)

## What it does

Overrides the default "speed by default" behavior for a single interaction when the user wants something explained or taught rather than just delivered. While active, it asks (once) how much depth the user wants, slows down, explains the what/why/context behind the work at that depth, offers to go deeper or move on after each explanation, and logs a cleaned-up writeup of each explanation as a new subpage under the Notion "Learning" index. It exits back to speed-mode immediately if the user signals they want to skip ahead, even mid-explanation.

## How to invoke it

Ask to have something explained, taught, or walked through — e.g. "explain this," "walk me through it," "help me understand," "why does this work this way," "break this down for me," "what's going on under the hood," "teach me." This skill is not invoked by default, and technical difficulty alone isn't a trigger — normal work proceeds at speed unless explanation is explicitly requested.

## What it produces

- Explanatory, depth-calibrated responses for the duration of the invocation.
- One new Notion subpage per explanation, filed under the "Learning" index page — a cleaned-up, durable writeup rather than a verbatim transcript.

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

## Version history

- **1.1.1** (EDS-7) — Added `SECURITY.md` (minimal "no trust boundary" template) to comply with `SKILL_FRAMEWORK.md`'s Physical Structure requirement, added in EDS-6. No behavioral change.
- **1.1.0** (EDS-5) — Broadened trigger vocabulary in the description itself, added explicit negative-trigger examples, added a mid-explanation opt-out, added a depth preference (short vs. in-depth), clarified Notion logs should be cleaned-up writeups.
- **1.0.0** (EDS-2) — Initial build.
