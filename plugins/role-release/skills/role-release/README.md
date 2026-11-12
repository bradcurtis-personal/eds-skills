# role-release

**Category:** System skill · **Rank:** 1 · **Layer:** none (system skills aren't layer-assigned)

## What it does

Closes the effort segment of the role an agent currently holds, by running `role-assume`'s `release` command, so that effort after this point is not attributed to that role (EDS-72 D3). A role switch needs no release: assuming the next role closes the previous segment. When no segment is open it reports a flag instead of failing, because effort outside a segment is recorded as `unassigned`.

## How to invoke it

Ask an agent to release its role, or have it invoke this skill when its role's work is done. The skill runs, from the folder of the `role-assume` skill:

```
python3 main.py release --agent <agent> [--session <id>]
```

with the same `--agent` and `--session` it gave `role-assume`. The skill is instruction-only; it has no logic file of its own, so the segment store and the rules stay in one place.

## What it produces

The closed segment as JSON (`released`: role, agent, ticket, open and close times), or `released: null` with a flag when no segment was open. Effort after the release is `unassigned` until a role is assumed again.

## Structure

| File | Purpose |
|---|---|
| `skill.json` | Metadata |
| `README.md` | This file |
| `SECURITY.md` | This skill's trust boundary |
| `test.py` | Acceptance test: the SKILL.md instruction, the dependency and the command it names |
| `SKILL.md` | Cowork-invocable packaging of this skill |

## Dependencies

- `role-assume`, which holds `main.py release` and the segment store. It ships as its own plugin, so install it alongside this one.

## Version history

- **1.0.0** (EDS-95) — Initial build: closes the segment through `role-assume`'s `release` command.
