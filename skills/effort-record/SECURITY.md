# Security

**Trust boundary:** Reads session transcripts and the role segment cache, and writes effort records to the `eds-data` ledger, but only through `ledger-append`. It opens no ledger file itself and runs no git command.

## What this skill touches

- Reads session transcript files passed with `--transcript` (read-only; only timestamps, message ids, model names and token counts are used, and message text is never copied out).
- Reads `segments.jsonl` in `role-assume`'s state directory (`~/.eds/role-segments`, or `--segments` / `EDS_ROLE_STATE_DIR`), read-only.
- Runs the `ledger-append` skill's `main.py` as a subprocess (the Python that is running this skill) to read and append events. That is the only way ledger data is touched.
- Writes a log file `logs/effort-record.log` in the working directory (standard logging bootstrap).
- No network calls, no secrets read or written, no Jira or GitHub access: it prints the `[EFFORT]` comment and the Actual usage (%) value, and the agent posts them under its own role.

## Why that's safe

- Everything it writes is validated by `ledger-append` against the record schema, and events use stable ids (derived from segment, model and ticket), so running `record` or `close` again changes nothing; a transcript that now gives a different token count is flagged, never written over the earlier line.
- Only closed segments are recorded, so a number is not written while its role is still working.
- Usage no segment claims is recorded as `unassigned`, never moved into a role; usage with no calibration factor is recorded without a percent and flagged, never guessed.

## Out of scope

- It cannot tell whether the segments are honest: a role declared wrongly in `role-assume` attributes effort wrongly (a DO-NOT-list matter that review and the `unassigned` figure can show).
- The calibration factors are rough (EDS-72 Open Decision 10); it uses them as they are and says which line it used.
- It does not post to Jira and does not set Actual usage (%) itself.
