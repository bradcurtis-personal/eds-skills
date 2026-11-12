# Security

**Trust boundary:** None of its own. This skill is instructions that run `role-assume`'s `release` command; the boundary (identity and permission decisions, the local segment cache) belongs to `role-assume` and is described in its `SECURITY.md`.

## What this skill touches

- Through `role-assume`: appends one `segment_close` line to `segments.jsonl` in the local state directory (`~/.eds/role-segments` by default). Nothing else, no network, no secrets, no repo files.

## Why that's safe

- Releasing only ever reduces what an agent is acting as: it closes a segment and grants no capability. The worst a wrong release does is leave later effort `unassigned`, which is flagged.

## Out of scope

- Everything `role-assume`'s `SECURITY.md` lists as out of scope. In particular, releasing a role does not revoke any credential; under `shared-po` the agent still holds Brad's, and the rule (not a system) is what stops it acting.

## High-leverage files

None. This skill has no logic file.
