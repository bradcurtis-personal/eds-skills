---
name: effort-record
description: "Use when a ticket's plan usage must be recorded per role, or its effort closed. Reads role segments and session transcripts, writes per-role effort events (percent of the weekly limit) plus an unassigned figure to the eds-data ledger through ledger-append, records an estimate, closes a ticket with delta, ratio and the [EFFORT] comment, and reports totals."
---

# effort-record

Measures work in the unit Brad cares about, percent of his plan's weekly limit (EDS-72 D5, D7, D8), per role (D3) with an `unassigned` bucket. It computes everything by code; nothing here is typed by hand. The ledger is reached only through the `ledger-append` skill, which must sit next to this one (or `EDS_LEDGER_APPEND` must name its `main.py`).

## When to invoke

- When a ticket's roles have all released their segments (`role-release`): `record`, then at close `close`.
- At pull-in, to record the estimate: `estimate`.
- Any time, for totals: `report`.

## Behavior while active

`main.py` is in the folder that contains this `SKILL.md`. Run it with `python3` (WSL on Brad's machine). Use `--ledger-dir <eds-data>/ledger` unless `EDS_LEDGER_DIR` is set.

1. **Estimate.** `python3 main.py estimate --ticket EDS-n --est-pct <expected percent>`.
2. **Record.** `python3 main.py record --ticket EDS-n --transcript <session.jsonl> [--transcript AGENT=<subagent.jsonl> ...]` (add `--dry-run` to look first). It appends one `effort` event per closed segment and model, and one `unassigned` event per model for usage in the ticket's period that no segment claims. `AGENT=FILE` limits a transcript to that agent's segments. Read the `flags` and report them as printed: an open segment, a model with no calibration (recorded without a percent, never guessed), a transcript that disagrees with an earlier record.
3. **Close.** `python3 main.py close --ticket EDS-n`. It sums the ticket's roles, computes delta and ratio against the estimate, appends a `close` event, and prints `comment` (the `[EFFORT] developer 2.1 | reviewer 0.8 | total 2.9 vs est 3` line) and `jira_actual_usage`. Post `comment` on the ticket and on the epic. Set Actual usage (%) to `jira_actual_usage` from the trial onward; during setup it stays empty (EDS-72 D5, D12).
4. **Report.** `python3 main.py report [--ticket EDS-n]` for per-ticket and overall totals, with unassigned apart.

Do not move tokens between roles, edit a ledger line, or add a field the schema lacks. A correction is a new event that refers to the earlier one in `note`. Percent uses rough calibration factors: say so when you quote it.
