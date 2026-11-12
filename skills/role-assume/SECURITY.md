# Security

**Trust boundary:** Identity and permission decisions for agent roles. `role-assume` tells an agent which identity and tier a role holds and refuses requests beyond them, but it does not issue, store or use any credential.

## What this skill touches

- Reads `role-registry.yaml` and `ROLE_REGISTRY.md` in the `engineering-design-system` clone (read-only).
- Reads session transcript files passed to `attribute` (read-only; only timestamps, message ids, model names and token counts are used, and message text is never copied out).
- Appends JSON lines to `segments.jsonl` in its state directory, `~/.eds/role-segments` by default (`EDS_ROLE_STATE_DIR` or `--state-dir` to change). The directory is outside every repo, a local cache.
- Writes a log file `logs/role-assume.log` in the working directory (standard logging bootstrap).
- No network calls, no shell commands, no secrets read or written. The registry records which account a role acts as (`shared-po`, `po-account`), never a token.

## Why that's safe

- The state directory holds only role names, agent names, ticket keys and timestamps. Appends are one whole line in one write, so a reader never sees a half line, and the file is never rewritten.
- A refusal is the default: an unknown, dormant or human role is not assumed; `check` allows only a tier at or below the role's own and only the identity in the role's record; with no role assumed, `check` denies.
- The tier vocabulary is read from `ROLE_REGISTRY.md`, so the skill cannot drift from the registry, and an unknown system or tier is an error rather than a pass.

## High-leverage files

`main.py`, specifically `cmd_assume` (who may be assumed) and `cmd_check` (what a role may do). A wrong-looking-right change there silently widens what an agent believes it may do, so any change to those functions needs Brad's diff review whether or not CI passes (`AUTONOMY_RANKS.md`, High-Leverage Files).

## Out of scope

- It cannot stop an agent from calling Jira, GitHub or any other system directly. Until each role has its own account (EDS-72 decision 19, gated), every agent role runs on Brad's credentials and the control is the rule plus the stamp, not a technical barrier.
- It does not authenticate the caller: `--agent` and `--role` are taken as declared. A caller that lies about them is a DO-NOT-list violation (`ROLE_REGISTRY.md`) that review and the ledger flags can show but this skill cannot prevent.
- Changing a role's tier or identity is a change to the registry, not to this skill.
