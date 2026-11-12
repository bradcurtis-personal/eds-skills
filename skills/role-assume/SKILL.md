---
name: role-assume
description: "Use when an agent must act as a team role (lead, developer, reviewer and so on): before starting role work, when switching role, when asked which role it is acting as, when it needs a permission check (tier or credential) or a request for the lead, or when splitting a session's usage by role. Declares the role, opens the effort segment, prints the stamp, identity, tiers and rules."
---

# role-assume

Gives an agent a declared role and keeps its effort attributed to it (EDS-72 D3). The role records and rules live in `engineering-design-system` (`role-registry.yaml`, `ROLE_REGISTRY.md`); this skill reads them and copies neither.

## When to invoke

- **Before any role work.** An agent with no declared role acts as nobody: its effort goes to `unassigned` and is flagged. Assume a role first. If you do not know which, ask the `lead` or Brad.
- **When the role changes.** Assuming a new role closes the old segment for you.
- **Before an action that needs a permission** the role may not hold (writing a Jira field, pushing, opening a PR): run `check` first.
- **When asked** which role you act as, or to split a session's usage by role: `status`, `attribute`.

Do not invoke it for a human role (Product Owner, Business Analyst) or a dormant one; it refuses both. To stop acting as a role, use `role-release`.

## Behavior while active

`main.py` is in the folder that contains this `SKILL.md`. Run it with `python3` (in WSL on Brad's machine; it needs PyYAML) from the `engineering-design-system` clone, or pass `--registry <path to role-registry.yaml>`. Use the same `--agent` name and `--session` id on every call.

1. **Assume.** `python3 main.py assume --role <id> --agent <agent> --ticket <EDS-n>`. Read the JSON it prints and then:
   - Start every Jira comment with the `stamp` (for example `[Developer]`) and put the `commit_trailer` (`Role: Developer`) on every commit message.
   - Act only under the `identities` and `tiers` it prints. They are the most the role may do.
   - Follow `role_assumption_rules` and `do_not_list`, and invoke the `plugin` skill for the role's own expectations if it is installed.
   - If it exits 2, read the `error`: the role is unknown, dormant or human. Do not act as that role and do not pick another to get around it.
2. **Check before you reach.** When an action needs a tier or identity, run `python3 main.py check --agent <agent> --system <jira|github|aws> --tier <tier>` (add `--identity <name>` when you are about to use a credential). Exit 0 means go ahead. Exit 3 means stop: the output holds a `request` addressed to the `lead` (to Brad when you are the `lead`). Post or hand over that request text as printed, wait for the answer, and do not get the capability another way. Never use another role's credentials, nor Brad's own account unless the role's record says `po-account` or `shared-po` for that system.
3. **Switch.** To act as another role, assume it. The previous segment closes at that moment and the new one opens.
4. **Release.** When the role's work is done, use `role-release`. Effort after a release, or before any assume, is `unassigned`.
5. **Attribute** (when asked, or at the end of a ticket). `python3 main.py attribute --transcript <session.jsonl> [--transcript <subagent.jsonl> ...] --agent <agent>` prints tokens per segment and per role. Tokens outside every segment are listed as `unassigned` with a flag. Report the flags as they are; do not move tokens between roles by hand.

Example: the `lead` hands a ticket to one agent that works as developer, then reviews as reviewer.

```
python3 main.py assume --role developer --agent a1 --ticket EDS-95
  ... work, commits carry "Role: Developer" ...
python3 main.py assume --role reviewer --agent a1 --ticket EDS-95
  ... review comments start with "[Reviewer]" ...
python3 main.py release --agent a1
python3 main.py attribute --transcript session.jsonl --agent a1
```

## Limits to state when relevant

While every role runs on Brad's credentials (`shared-po`), this is enforced by rule, not by the systems; say so rather than implying a hard barrier. The skill records segments in a local cache and does not write the ledger (EDS-77 does).
