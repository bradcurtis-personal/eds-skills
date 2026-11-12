# budget-guard

**Category:** System skill · **Rank:** 1 · **Layer:** none (system skills aren't layer-assigned)

## What it does

Keeps agent runs and sprints inside the usage ceilings (EDS-72 D6): a run stops and reports at 75% of the five-hour window, and a sprint is reported against its cap of 30% of the weekly limit. There is no confirmed automatic live source for the five-hour percentage (decision 30(j)), so the skill reads it from layered sources, names the one it used, and says so when none is available instead of guessing.

- **check.** Tries sources in order and uses the first that works:
  1. **status-line**: a JSON file with `rate_limits.five_hour.used_percentage` and `resets_at` (`--status-file` or `EDS_STATUS_FILE`). Used only if a status line ever writes one; it did not run in the Desktop Code tab. Confidence high.
  2. **manual**: the newest reading stored with `reading` (whole percent from Settings > Usage, with its time and the window's reset time), if it is no older than `--max-age-min` (60) and its window has not reset. With `--transcript` files it adds the transcript tokens since the reading, converted with the five-hour calibration factor (`manual+transcript`). Confidence medium; a model with no factor (Opus) makes it a lower bound.
  3. **transcript**: tokens inside the window (reset time minus five hours up to now) divided by the five-hour factor. A lower bound only, because usage outside the given transcripts, claude.ai chat included, is invisible. Confidence low.

  The verdict is `stop` at or above the threshold (75 by default; a lower bound at or above it is still a certain stop), `ok` when a non-lower-bound reading is below it, `unverified` when only a lower bound is below it, and `unavailable` when no source works. Every answer lists the sources tried and why each was or was not used.
- **reading.** Stores a manual reading in a local cache outside every repo.
- **sprint.** Sums the sprint's `effort` events from the ledger (percent of the weekly limit per role, `unassigned` apart, through `ledger-append`) and compares the total with the cap (30 by default). It reports the total, the share of the cap and the remainder, and flags tokens with no calibration factor as a lower bound. No events for the sprint is `unavailable`, never zero.

## How to invoke it

Run from `skills/budget-guard/` in the `eds-skills` checkout, or from the installed plugin, with `python3` (in WSL on Brad's machine). Standard library only. The `ledger-append` skill must sit next to it, or `EDS_LEDGER_APPEND` must name its `main.py`.

```
python3 main.py reading --percent 40 --resets-at 2026-11-12T23:00:00Z [--at <ISO time>]
python3 main.py check   [--threshold 75] [--max-age-min 60] [--status-file F] [--transcript FILE ...] [--window-resets TS]
python3 main.py sprint  --sprint "<name>" [--cap 30]
```

Add `--ledger-dir <eds-data>/ledger` unless `EDS_LEDGER_DIR` is set. Readings live in `$EDS_BUDGET_STATE_DIR/readings.jsonl`, or `~/.eds/budget-guard/readings.jsonl`. `--now` replays a check at a given time. Exit codes: 0 ok, 2 refused (the JSON `error` says why), 3 stop (`stop` or `over_cap`), 4 unavailable or unverified.

## What it produces

JSON on stdout. `check` prints `verdict`, `five_hour_pct`, `threshold_pct`, `source`, `confidence`, `lower_bound`, `reading_at`, `window_resets_at`, `tried`, `flags` and a one-line `message` beginning OK, STOP, UNVERIFIED or UNAVAILABLE. `sprint` prints `by_role_pct`, `unassigned_pct`, `total_pct`, `cap_pct`, `share_of_cap_pct`, `remaining_pct`, `verdict`, `flags` and `message`. `reading` prints the stored line. The skill cannot halt a session: the stop is the exit code and message, which the agent and its role plugin obey. It writes nothing to the ledger and does not call Jira.

## Structure

| File | Purpose |
|---|---|
| `skill.json` | Metadata |
| `main.py` | This skill's logic |
| `README.md` | This file |
| `SECURITY.md` | This skill's trust boundary |
| `test.py` | Acceptance test: the stop at 75% (each source), ok below it, stale and reset readings, unavailable and unverified paths, Opus lower bound, deduplication, sprint total against the cap |
| `SKILL.md` | Cowork-invocable packaging of this skill |

## Dependencies

- `ledger-append` (reads calibration and effort events; needed for transcript conversion and for `sprint`).
- Five-hour calibration lines in the `eds-data` ledger (`effort-record`'s README, EDS-77). Without one for a model, that model's tokens are counted as uncalibrated, never guessed.

## Known limits

- **No automatic live source today.** A manual reading is the only fresh source until a status line payload is confirmed (decision 30(j)). A reading is good for 60 minutes and accurate to about one point (Settings > Usage shows whole percents).
- **Transcript estimates are lower bounds.** They cannot see usage outside the transcripts given, and factors are rough (EDS-72 Open Decision 10). Opus has no factor, so its tokens are uncalibrated.
- **It cannot stop a session itself.** The role plugin or agent must act on exit 3; under a shared account nothing else enforces it.
- **The sprint total is only as complete as the ledger.** Run `effort-record record --sprint` for each ticket first; usage not yet recorded is not in it.
- Logging follows the standard bootstrap: a `logs/budget-guard.log` file in the working directory.

## Version history

- **1.0.0** (EDS-96) — Initial build: `reading`, `check` and `sprint`; layered five-hour sources with named provenance (status-line, manual, transcript), the 75% stop (exit 3), unavailable and unverified answers instead of guesses, and sprint usage against the 30% cap.
