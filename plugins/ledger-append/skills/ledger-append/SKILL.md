---
name: ledger-append
description: "Use when an event must go into, or be read from, the eds-data ledger (effort, estimate, close or calibration events), or when appended ledger lines must be committed to eds-data main. Validates the event against the record schema, appends it, reads events back, and makes the data-only commit eds-data allows. The only code that opens ledger files."
---

# ledger-append

The one reader/writer module for the `eds-data` ledger (EDS-72 D8, EDS-76). Other skills, including `effort-record`, call it and never open ledger files themselves. The record format is `docs/RECORD_SCHEMA.md` in `eds-data`; this skill mirrors it and refuses anything it does not define.

## When to invoke

- To append one event (`append`), read events back (`read`), or commit and push what was appended (`commit`). Most agents do not call it directly: `effort-record` does.
- Never to write a field the schema lacks. That is a schema change: a branch and PR in `eds-data` and Brad's merge.

## Behavior while active

`main.py` is in the folder that contains this `SKILL.md`. Run it with `python3` (in WSL on Brad's machine) and find the ledger with `--ledger-dir`, `EDS_LEDGER_DIR` or a sibling `eds-data` clone.

1. **Append.** `python3 main.py append --event '<json>'` (or `--event-file`). It fills `event_id`, `schema_version` and `ts` when missing, validates, and appends to `ledger/YYYY-MM.jsonl` (or `ledger/calibration.jsonl`). Exit 2 with an `error` means the event was refused: fix the event, do not work around it. `"appended": false` means the `event_id` was already there.
2. **Read.** `python3 main.py read [--ticket EDS-n] [--event effort|estimate|close|calibration]` prints the events oldest first.
3. **Commit.** `python3 main.py commit --repo <eds-data clone> [--message "..."] [--push]`. It commits only when the branch is `main`, every changed path is under `ledger/` or `reports/`, and no existing line was changed. Run it in WSL when using `--push`. If it refuses, tell Brad; do not stage by hand.

Report refusals as printed. Never edit or delete a ledger line: a correction is a new event that refers to the earlier one in `note`.
