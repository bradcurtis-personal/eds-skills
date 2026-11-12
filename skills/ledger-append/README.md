# ledger-append

**Category:** System skill · **Rank:** 3 · **Layer:** none (system skills aren't layer-assigned)

## What it does

The one reader/writer module for the `eds-data` ledger (EDS-72 D8; storage decided in EDS-76). It validates an event against the record schema, appends it to the right file, reads events back, and makes the data-only commit to `main` that `eds-data`'s `CLAUDE.md` allows. Nothing else opens ledger files: `effort-record` and every other skill go through this one.

- **Validation.** An event must have `event` (`effort`, `estimate`, `close` or `calibration`), its required fields and no field the schema does not define. A field that is not in `docs/RECORD_SCHEMA.md` is a schema change (a PR to `eds-data`), so it is refused here. `event_id`, `schema_version` and `ts` are filled in when absent.
- **Append-only, idempotent.** A line is written whole in one `O_APPEND` write and never rewritten. An `event_id` already in the file is a no-op, so importing the same event twice changes nothing.
- **Partitioning.** Effort, estimate and close events go to `ledger/YYYY-MM.jsonl` by the month of `ts` (UTC); calibration events go to `ledger/calibration.jsonl`.
- **Reading.** `read` returns every event oldest first, with `event` inferred for any version 1 line that lacks it.
- **Committing.** `commit` stages and commits only when the repo is `eds-data`, the branch is `main`, every changed path is under `ledger/` or `reports/`, and no existing line was changed. `--push` then pushes `main`.

## How to invoke it

Run from `skills/ledger-append/` in the `eds-skills` checkout, or from the installed plugin, with `python3` (in WSL on Brad's machine; the Windows host has no Python). Standard library only.

```
python3 main.py append --event '{"event":"estimate","ticket":"EDS-77","est_pct":3}' [--ledger-dir <eds-data>/ledger]
python3 main.py append --event-file event.json
python3 main.py read [--ticket EDS-77] [--event effort]
python3 main.py commit --repo <eds-data clone> [--message "data: ..."] [--push]
```

The ledger directory is `--ledger-dir`, then `EDS_LEDGER_DIR`, then `./ledger`, then a sibling `eds-data` clone. Exit codes: 0 done, 2 refused (the JSON `error` says why).

## What it produces

JSON on stdout for every command. `append` prints `{"appended": true|false, "file": ..., "path": ...}`; `read` prints `{"count": n, "events": [...]}`; `commit` prints `{"committed": ..., "paths": [...], "pushed": ...}`. The ledger lines themselves are JSON Lines in `eds-data`, in the format `docs/RECORD_SCHEMA.md` defines (`schema_version` 2).

## Structure

| File | Purpose |
|---|---|
| `skill.json` | Metadata |
| `main.py` | This skill's logic |
| `README.md` | This file |
| `SECURITY.md` | This skill's trust boundary and its high-leverage file |
| `test.py` | Acceptance test: validation, append, idempotence, partitioning, reading, and the data-only commit rules on a throwaway git repo |
| `SKILL.md` | Cowork-invocable packaging of this skill |

## Dependencies

- The `eds-data` repo: `docs/RECORD_SCHEMA.md` is the format this skill mirrors (`test.py` fails if the field lists drift apart when the schema is reachable), and `commit` writes to its clone.
- `git` for `commit`. No third-party Python packages.

## Known limits

- **The rank is 3 because of `commit`.** A direct commit and push to `main` is the riskiest thing it does, allowed only for data in `eds-data` (EDS-76). `append` alone is local.
- **No ruleset guards `eds-data` `main`.** The checks in `commit` are the only guard; a push made outside this skill is not blocked.
- **It cannot tell a true event from a false one.** It checks the shape, not the facts. `effort-record` is what computes events from transcripts.
- **One writer at a time per file.** Two machines appending to the same month file and pushing at once can collide; the second push is refused and reported, and nothing is merged for you.
- **Duplicate check reads one file.** `event_id` is checked within the target file only. Events with the same id and a different month would both be written, which cannot happen when the id is derived from the event.
- Logging follows the standard bootstrap: a `logs/ledger-append.log` file in the working directory.

## Version history

- **1.0.0** (EDS-77) — Initial build: `append`, `read` and `commit`; validation against schema version 2; monthly partitioning; data-only commit guard.
