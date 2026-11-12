---
name: budget-guard
description: "Use before starting or continuing an agent run, at each segment boundary, and when planning or closing a sprint, to keep usage inside the ceilings (EDS-72 D6). Reads the five-hour percentage from the best available source (status-line file, a manual reading from Settings > Usage, or a transcript estimate), stops the run and reports at 75%, says so when no reading is available instead of guessing, and reports a sprint's usage against its 30% cap of the weekly limit."
---

# budget-guard

Keeps agent runs and sprints inside the usage ceilings (EDS-72 D6): stop at 75% of the five-hour window, and at most 30% of the weekly limit per sprint. There is no confirmed automatic live source for the five-hour percentage (decision 30(j)), so `check` tries three sources in order and names the one it used. It never guesses.

## When to invoke

- Before a role starts a run, and at each segment boundary (before `role-assume` switches roles or a new ticket starts): `check`.
- When Brad reads Settings > Usage ("Current session"): `reading`.
- When planning or closing a sprint, or before pulling more work in: `sprint`.

## Behavior while active

`main.py` is in the folder that contains this `SKILL.md`. Run it with `python3` (WSL on Brad's machine). Use `--ledger-dir <eds-data>/ledger` unless `EDS_LEDGER_DIR` is set. The `ledger-append` skill must sit next to this one (or `EDS_LEDGER_APPEND` must name its `main.py`).

1. **Reading.** Ask Brad for the "Current session" percent and when it resets, then `python3 main.py reading --percent <n> --resets-at <ISO time>`. A reading is good for 60 minutes (`--max-age-min`) and until its window resets.
2. **Check.** `python3 main.py check [--transcript <session.jsonl> ...]`. Sources, best first: a status-line file (`--status-file` or `EDS_STATUS_FILE`, only if one exists), the newest manual reading (plus transcript tokens since it, when transcripts are given), then a transcript estimate, which is a lower bound only. Read `message`, `source`, `confidence` and `flags` and report them as printed.
   - Exit 0, `ok`: carry on.
   - Exit 3, `stop`: at or above 75%. Stop the run, finish no new work and report to the `lead` (to Brad if you are the `lead`) with the state of the ticket. Do not start another run until the window resets or Brad says to go on.
   - Exit 4, `unavailable` or `unverified`: there is no reading, or only a lower bound under the threshold. Say so, ask Brad for a reading, and check again. Do not treat it as ok.
3. **Sprint.** `python3 main.py sprint --sprint <name>`. Totals the sprint's effort events (percent of the weekly limit, `unassigned` apart) against the cap of 30. Exit 3, `over_cap`, means stop pulling work in and report to the `lead`. Exit 4 means nothing was recorded for the sprint: run `effort-record record --sprint` first.

Percentages from transcripts use rough calibration factors, and Opus has none: say so when you quote them. Do not edit `readings.jsonl`; a correction is a new reading.
