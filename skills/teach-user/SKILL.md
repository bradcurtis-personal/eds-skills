---
name: teach-user
description: Shifts into explanation/teaching mode for one interaction when the user wants something explained or taught rather than just delivered — slows down, explains what's being done and why, and logs the explanation to Notion.
---

# Teach User

## When to invoke

Invoke this skill when the user explicitly asks for something to be explained, taught, or walked through — not by default. Examples: "explain how this works," "can you teach me about X," "what does this command actually do," "walk me through this." Do not invoke this proactively; the default mode favors speed over explanation unless this skill is triggered.

## Behavior while active

1. **Slow down.** Override default speed-mode for this interaction. Prioritize clarity over brevity.
2. **Explain what and why.** Don't just describe *what* is being done — explain *why* it's being done this way, what the alternatives were, and what would break if it were done differently.
3. **Give context.** Briefly cover the underlying technology or concept so the explanation doesn't assume knowledge the user hasn't confirmed they have.
4. **Offer to go deeper or move on.** After each explanation, ask whether the user wants more detail or is ready to continue. Don't assume.
5. **Log the explanation.** Create one new subpage under the Notion "Learning" index page for this explanation (title it clearly after the topic). Dump the explanation's content into that subpage.
6. **Return to speed-mode.** When the user signals they've understood or wants to move on (e.g. "got it," "let's continue," "moving on"), exit teaching mode and resume default speed-mode for the rest of the session.

## What this skill does not do

- It does not change what work gets done — only how much is explained along the way.
- It does not persist as a standing mode across the whole session — it applies to the interaction(s) it's invoked for, until the user signals they're done with that explanation.
