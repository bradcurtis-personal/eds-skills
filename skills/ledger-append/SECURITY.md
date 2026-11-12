# Security

**Trust boundary:** Writes to the `eds-data` repo's ledger and, on request, commits and pushes straight to its `main`. That is the one place a skill may commit to `main` without a PR, so the skill itself enforces the data-only rule `eds-data`'s `CLAUDE.md` states.

## What this skill touches

- Appends JSON lines to `ledger/YYYY-MM.jsonl` and `ledger/calibration.jsonl` in the `eds-data` clone, and reads those files (the only code that opens them).
- `commit` runs `git status`, `git diff --numstat`, `git add`, `git commit` and, with `--push`, `git push origin main` in the `eds-data` clone. No other git operation, no `gh`.
- Writes a log file `logs/ledger-append.log` in the working directory (standard logging bootstrap).
- No network calls other than `git push`, no secrets read or written. Events hold ticket keys, role names, model names, token counts and percentages.

## Why that's safe

- Every event is validated against the schema before it is written: unknown fields, wrong types and missing required fields are refused, so a field the schema does not define cannot reach the ledger (adding one is a PR to `eds-data`).
- Appends are one whole line in one write on an `O_APPEND` handle, and an existing line is never rewritten. A repeated `event_id` is a no-op.
- `commit` refuses unless the repo has `docs/RECORD_SCHEMA.md`, the branch is `main`, every changed path is under `ledger/` or `reports/`, and no existing line was removed or changed. A mixed or structural diff is refused with the list of offending paths.

## High-leverage files

`main.py`, specifically `cmd_commit` (what may reach `main` without review) and `validate` (what may enter the ledger). A change to either needs Brad's diff review whether or not CI passes (`AUTONOMY_RANKS.md`, High-Leverage Files).

## Out of scope

- It does not authenticate who calls it or check that an event is true: a caller can append a made-up `effort` line that fits the schema. Truth comes from `effort-record` computing events from transcripts and from the Reviewer's reading of the ledger.
- `eds-data` has no ruleset on `main` (see its `CLAUDE.md`), so nothing blocks a direct push made outside this skill.
- It does not merge concurrent writers: two machines appending to the same month file and pushing at once can collide; the second push fails and is reported.
