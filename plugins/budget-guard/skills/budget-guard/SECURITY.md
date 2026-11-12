# Security

**Trust boundary:** Reads session transcripts and the `eds-data` ledger (through `ledger-append`), and writes one local cache of manual usage readings outside every repo. It cannot stop a session itself: it prints a verdict and exits with a code that the agent obeys.

## What this skill touches

- Reads transcript files passed with `--transcript` (read-only; only timestamps, message ids, model names and token counts are used, and message text is never copied out).
- Reads an optional status-line JSON file named by `--status-file` or `EDS_STATUS_FILE` (read-only; only `rate_limits.five_hour`).
- Appends to `readings.jsonl` in its state directory (`~/.eds/budget-guard`, or `--state-dir` / `EDS_BUDGET_STATE_DIR`): a reading's time, percent and window reset time, nothing else.
- Runs the `ledger-append` skill's `main.py` as a subprocess, with its `read` command only, to read calibration and effort events. It never appends to the ledger and runs no git command.
- Writes a log file `logs/budget-guard.log` in the working directory (standard logging bootstrap).
- No network calls, no secrets read or written, no Jira or GitHub access.

## Why that's safe

- The only write outside its own log is one small append-only local file holding no secrets or personal data. The ledger is read, never written.
- A reading it cannot take is reported as unavailable, and a lower bound under the threshold is reported as unverified, so a missing source cannot pass as "ok".
- Stale readings (older than the limit, or from a window that has reset) are refused, and factors with no calibration line (Opus today) are counted as uncalibrated tokens, never converted by a guess.

## Out of scope

- It cannot force an agent to stop: the stop is a rule the agent and its role plugin follow when it sees exit 3. Under a shared account nothing enforces it beyond that rule.
- A reading typed wrongly, or a transcript set that leaves out other usage (claude.ai chat, other sessions), makes the number wrong; the output says which source it used and whether it is a lower bound.
- The calibration factors are rough (EDS-72 Open Decision 10); it uses them as they are and names the line used.
