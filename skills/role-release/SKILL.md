---
name: role-release
description: "Use when an agent is done acting as a team role, or is about to stop work: closes the effort segment the agent holds so later effort is not attributed to that role. Runs role-assume's release command."
---

# role-release

Ends the role an agent assumed with `role-assume` (EDS-72 D3). Leaving a role closes its effort segment; effort after that is `unassigned` until a role is assumed again.

## When to invoke

- The role's work is finished (ticket handed off, review posted) and the agent will keep working without a role, or stop.
- The agent hands back to the `lead` or Brad.
- Not for a role switch: assuming the next role with `role-assume` closes the old segment by itself.

## Behavior while active

1. Run `role-assume`'s release command, with the same `--agent` name and `--session` id used when the role was assumed:

   ```
   python3 main.py release --agent <agent> [--session <id>]
   ```

   `main.py` is in the `role-assume` skill's folder (the `eds-skills` checkout's `skills/role-assume/`, or the installed `role-assume` plugin). It needs PyYAML (WSL `python3` on Brad's machine). This skill depends on `role-assume` being installed.
2. Read the JSON. `released` holds the closed segment (role, ticket, open and close times). Say which role was released.
3. If `released` is `null`, nothing was open: report the `flag` as it is. The effort since the last release, or since the session began, is `unassigned`; do not assume a role after the fact to cover it.
4. After the release, stop using the role's stamp, trailer and permissions. Work that still needs a role means assuming one with `role-assume` first.
