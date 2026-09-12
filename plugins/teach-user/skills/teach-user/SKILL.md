---
name: teach-user
description: Shifts into explanation/teaching mode when the user wants something explained, taught, or walked through rather than just delivered — triggers on phrasing like "explain this," "walk me through it," "help me understand," "why does this work this way," "break this down for me," "what's going on under the hood," or "teach me." Slows down, explains what's being done and why, and logs the explanation to Notion. Does not trigger just because a task is technical or complex — only on an explicit request for explanation.
---

# Teach User

## When to invoke

Invoke this skill when the user explicitly asks for something to be explained, taught, or walked through. Trigger phrasing includes: "explain how this works," "can you teach me about X," "what does this command actually do," "walk me through this," "help me understand," "why does this work this way," "break this down for me," "what's going on under the hood."

Do not invoke this:
- Proactively, by default — the default mode favors speed over explanation unless this skill is triggered.
- Just because a task is technical, complex, or multi-step — technical difficulty alone isn't a signal the user wants a lesson.
- For a simple factual lookup ("what version of X do I have," "what does this error say") — that's an answer, not a teaching request.

## Behavior while active

1. **Ask for depth, if not already clear.** If the user hasn't indicated how much detail they want, ask once: short version, or in depth? Use their answer to calibrate every explanation for the rest of the invocation, without re-asking each time.
2. **Slow down.** Override default speed-mode for this interaction. Prioritize clarity over brevity, scaled to the depth the user asked for.
3. **Explain what and why.** Don't just describe *what* is being done — explain *why* it's being done this way, what the alternatives were, and what would break if it were done differently.
4. **Give context.** Briefly cover the underlying technology or concept so the explanation doesn't assume knowledge the user hasn't confirmed they have.
5. **Offer to go deeper or move on.** After each explanation, ask whether the user wants more detail or is ready to continue. Don't assume.
6. **Log the explanation.** Create one new subpage under the Notion "Learning" index page for this explanation (title it clearly after the topic). Write a cleaned-up, durable version of the explanation into that subpage — organized and readable as a future reference, not a verbatim chat transcript.
7. **Exit immediately on an opt-out signal.** If at any point — even mid-explanation — the user signals they want to skip ahead (e.g. "just do it," "skip the explanation," "never mind, continue"), drop back to speed-mode right away rather than finishing the explanation in progress.
8. **Return to speed-mode.** When the user signals they've understood or wants to move on (e.g. "got it," "let's continue," "moving on"), exit teaching mode and resume default speed-mode for the rest of the session.

## What this skill does not do

- It does not change what work gets done — only how much is explained along the way.
- It does not persist as a standing mode across the whole session — it applies to the interaction(s) it's invoked for, until the user signals they're done with that explanation (including mid-explanation opt-outs).
