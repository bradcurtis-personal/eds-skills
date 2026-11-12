# effort-record

**Category:** System skill · **Rank:** 1 · **Layer:** none (system skills aren't layer-assigned)

## What it does

Measures work in the unit Brad cares about: percent of his plan's weekly limit (EDS-72 D5), per role (D3), per ticket and overall, with an `unassigned` bucket for usage no role can claim. Everything is computed by code from session transcripts and role segments (D7, D8); delta and ratio are never typed by hand. It reads and writes the ledger only through the `ledger-append` skill.

- **record.** Reads `role-assume`'s segments (`segments.jsonl`) and the session transcripts, drops the duplicate transcript lines (each API message is written twice, so it dedupes by `message.id`), and puts each message in the segment open at its timestamp (half-open: `[open, close)`). It appends one `effort` event per closed segment and model, with tokens (input, output, cache-creation and cache-read summed) and `usage_pct`. Usage inside the ticket's period (first segment open to last segment close) that no segment claims becomes one `unassigned` event per model. An open segment is flagged and not recorded; the unassigned figure waits until all the ticket's segments are closed.
- **Conversion.** `usage_pct` is tokens divided by the model's tokens-per-1% of the weekly limit, from the newest calibration line in the ledger (a `weekly` line, or a `five_hour` line divided by the newest `ratio` line, with the model matched as a prefix, longest first). The line used is named in `factor_id`. A model with no calibration (Opus today) is recorded with its tokens, no `usage_pct`, and a flag: it is never guessed, and its tokens are not in any percent total.
- **estimate.** Records the ticket's expected share of the weekly limit.
- **close.** Sums the ticket's role percentages (unassigned apart), computes `delta_pct` and `ratio` against the latest estimate, appends a `close` event and prints the compact `[EFFORT]` comment, for example `[EFFORT] developer 2.1 | reviewer 0.8 | lead 0.4 | total 3.3 vs est 3`, plus `unassigned` when there is some, and the value for Jira's Actual usage (%).
- **report.** Per-ticket and overall percent, per role, with unassigned apart and the grand total.

Dormant roles accrue nothing because `role-assume` refuses to open a segment for one.

## How to invoke it

Run from `skills/effort-record/` in the `eds-skills` checkout, or from the installed plugin, with `python3` (in WSL on Brad's machine). Standard library only. The `ledger-append` skill must sit next to it, or `EDS_LEDGER_APPEND` must name its `main.py`.

```
python3 main.py estimate --ticket EDS-77 --est-pct 3 [--sprint S]
python3 main.py record   --ticket EDS-77 --transcript <session.jsonl> [--transcript AGENT=<subagent.jsonl> ...] [--dry-run]
python3 main.py close    --ticket EDS-77
python3 main.py report   [--ticket EDS-77]
```

Add `--ledger-dir <eds-data>/ledger` unless `EDS_LEDGER_DIR` is set. The segment file is `--segments`, then `$EDS_ROLE_STATE_DIR/segments.jsonl`, then `~/.eds/role-segments/segments.jsonl`. `AGENT=FILE` limits a transcript to that agent's segments; a bare `FILE` matches any agent's. Exit codes: 0 done, 2 refused (the JSON `error` says why).

## What it produces

JSON on stdout. `record` prints the events appended and `flags`; `close` prints `by_role_pct`, `unassigned_pct`, `total_pct`, `estimate_pct`, `delta_pct`, `ratio`, `comment` and `jira_actual_usage`; `report` prints `tickets` and `overall`. The events themselves are in `eds-data` (`schema_version` 2, `docs/RECORD_SCHEMA.md`). The agent posts `comment` on the ticket and its epic and sets Actual usage (%) to `jira_actual_usage` from the trial onward; during setup that field stays empty (EDS-72 D5, D12). The skill does not call Jira.

## Structure

| File | Purpose |
|---|---|
| `skill.json` | Metadata |
| `main.py` | This skill's logic |
| `README.md` | This file |
| `SECURITY.md` | This skill's trust boundary |
| `test.py` | Acceptance test: three roles and an unassigned gap from one transcript, deduplication, idempotence, close with delta and ratio, open segments, uncalibrated models, calibration lookup |
| `SKILL.md` | Cowork-invocable packaging of this skill |

## Dependencies

- `ledger-append` (the only reader/writer of the ledger).
- `role-assume`'s segment file format (`segments.jsonl`, documented in its README); this skill reads it and does not call `role-assume`.
- Calibration lines in the `eds-data` ledger. Until a line exists for a model, that model's events have no percent.

## Known limits

- **Early numbers are rough.** The tokens-per-1% factors are provisional (EDS-72 Open Decision 10): one cache-heavy workload, whole-percent readings, and a weekly-to-five-hour ratio that is not known to be constant. Percentages are indicative, and a `measured` factor replaces a `provisional` one by adding a newer calibration line, not by rewriting history. Quote percentages as rough.
- **Opus is uncalibrated** until it is measured; its tokens appear in the ledger without a percent and the report counts them as `uncalibrated_tokens`.
- **The unassigned figure is the whole period's.** It covers usage between a ticket's first segment open and last segment close that no segment claims, which can include time spent on other things. It is flagged for investigation, not attributed. Usage outside every ticket's period is not recorded by this skill.
- **Recorded once per closed segment.** A transcript that later gives a different token count is flagged and not rewritten; correct it with a new event that refers to the earlier one in `note`.
- **Transcripts must be given.** The skill does not find them; the caller passes the main transcript and each subagent's file, with `AGENT=` when concurrent roles could overlap in time.
- **Effort attribution for PO/BA-invoked skills (Open Decision 8) is undecided.** Their usage has no role segment and lands in `unassigned`.
- Logging follows the standard bootstrap: a `logs/effort-record.log` file in the working directory.

## Version history

- **1.0.0** (EDS-77) — Initial build: `estimate`, `record`, `close` and `report`; per-role usage from segments and transcripts, converted with versioned calibration lines; an unassigned figure; the `[EFFORT]` closing comment.
