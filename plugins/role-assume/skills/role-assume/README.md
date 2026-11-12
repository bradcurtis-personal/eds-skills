# role-assume

**Category:** System skill · **Rank:** 1 · **Layer:** none (system skills aren't layer-assigned)

## What it does

Lets an agent declare the role it assumes and have its effort attributed to that role (EDS-72 D3). `role-assume` reads the role's record from `role-registry.yaml` in `engineering-design-system`, refuses a role that is unknown, dormant or human, closes any segment the agent already holds (a role switch), opens a new effort segment, and prints what the agent needs to act as the role: the stamp (`[Developer]`), the commit trailer (`Role: Developer`), the role's identities, tiers and default model, the role plugin to invoke, and the role-assumption rules and DO-NOT list read from `ROLE_REGISTRY.md`. It copies none of that; the registry stays the one source.

The same `main.py` also closes a segment (`release`, used by the `role-release` skill), shows the open segment (`status`), answers permission questions (`check`) and splits transcript usage by segment (`attribute`).

- **Tier and credential checks.** `check --system jira --tier write` says whether the assumed role's tier reaches that level. `check --system github --identity po-account` says whether that identity is the role's own. A refusal exits 3 and prints a request addressed to the `lead` (to the Product Owner when the `lead` is the one asking), written with the role's stamp, and logs the request as an event. The agent sends that request and does not obtain the capability another way.
- **Attribution.** `attribute` reads one or more session transcripts, drops the duplicate lines (each API message is written twice, so it dedupes by `message.id`), and puts each message's tokens in the segment that was open at its timestamp. Segments are half-open: a segment owns `[open, close)`, so a message stamped at a switch belongs to the new role. A message outside every segment goes to `unassigned` and is flagged, so no effort is silently absorbed into a role. An agent with no declared role has everything `unassigned`.

## How to invoke it

Run from `skills/role-assume/` in the `eds-skills` checkout, or from the installed plugin, with the Python that has PyYAML (in WSL: `python3`).

```
python3 main.py assume  --role developer --agent <agent> --ticket EDS-95 [--session <id>]
python3 main.py status  --agent <agent> [--session <id>]
python3 main.py check   --agent <agent> --system jira --tier write
python3 main.py check   --agent <agent> --system github --identity po-account
python3 main.py release --agent <agent> [--session <id>]
python3 main.py attribute --transcript <session.jsonl> [--transcript <agent-x.jsonl> ...] [--agent <agent>]
```

Use the same `--agent` and `--session` on every call: the pair is how a segment is found. The registry is found from `--registry`, then `EDS_REGISTRY`, then `./role-registry.yaml`, then a sibling `engineering-design-system` clone. `--now <ISO 8601 UTC>` pins the clock for tests and replay. Exit codes: 0 done, 2 refused (the JSON `error` says why), 3 denied by `check`.

## What it produces

JSON on stdout for every command. Segment events (`segment_open`, `segment_close`, `capability_request`), one JSON object per line with `event_id`, `schema_version` and `ts`, are appended to `segments.jsonl` in the state directory: `~/.eds/role-segments` by default, `EDS_ROLE_STATE_DIR` or `--state-dir` to change it. That directory is a local cache outside every repo, so nothing is committed. The skill does not write the ledger: turning segment tokens into the percentage and appending effort events to `eds-data` is EDS-77's job, and it reads these segments.

### Segment file format (the contract EDS-77 reads)

One JSON object per line, append-only, each with `event_id`, `schema_version` (1), `ts` (ISO 8601 UTC) and `event`:

| `event` | Other fields |
|---|---|
| `segment_open` | `segment_id`, `role` (the role's `ledger_key`), `agent`, `session`, `ticket` |
| `segment_close` | `segment_id`, `reason` (`release` or `switch`) |
| `capability_request` | `segment_id`, `role`, `to`, `system`, `tier`, `text` |

A segment with no `segment_close` is open. Because the file is a local cache and not part of `eds-data`, `docs/RECORD_SCHEMA.md` there is unchanged; EDS-77 decides what from these segments reaches the ledger and updates that schema then.

## Structure

| File | Purpose |
|---|---|
| `skill.json` | Metadata |
| `main.py` | This skill's logic |
| `README.md` | This file |
| `SECURITY.md` | This skill's trust boundary and its high-leverage file |
| `test.py` | Acceptance test: assume, refuse, switch, release, checks, and a two-role attribution run |
| `SKILL.md` | Cowork-invocable packaging of this skill |

## Dependencies

- PyYAML, to read `role-registry.yaml`. CI installs it from the repo's `requirements.txt`.
- `role-registry.yaml` and `ROLE_REGISTRY.md` in the `engineering-design-system` repo. The tier vocabulary is read from the tier table in `ROLE_REGISTRY.md`, not copied.
- `role-release` calls this skill's `release` command.

## Known limits

- **No technical credential barrier yet.** Every agent role runs on `shared-po` (Brad's credentials with the role stamped on its work, EDS-72 decision 19), so nothing stops a determined agent from calling Jira or GitHub outside `check`. The skill enforces by rule: it refuses dormant and human roles, answers tier and identity questions, and turns a refusal into a request to the `lead`. Hard enforcement waits for per-role accounts.
- **Segments are found by agent and session.** A caller that changes either value between calls will not find its open segment. Open segments are never closed for you: a crashed session leaves one open, and `attribute` flags it and counts it up to the last message.
- **Timestamps decide attribution.** Overlapping segments for different agents are separated by `--agent`; two roles open at once for the same agent and session are not a supported state (an `assume` closes the previous one).
- **Transcript shapes.** `attribute` reads records with a `timestamp` (or `ts`) and a `message` carrying `usage`; it covers the main transcript and subagent files. It sums input, output, cache-creation and cache-read tokens as `total_tokens` and lists the fields it summed. Weighting them, per model, into a percentage of the weekly limit is EDS-77.
- Logging follows the standard bootstrap: a `logs/role-assume.log` file in the working directory.

## Version history

- **1.0.0** (EDS-95) — Initial build: `assume`, `release`, `status`, `check` and `attribute`; segment events kept in a local cache; test shows two roles used in sequence by one agent with usage split by segment.
