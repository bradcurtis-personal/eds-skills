---
name: skill-create
description: Scaffolds a new skill folder that already conforms to SKILL_FRAMEWORK.md, or audits an existing skill against current standards and reports what's stale.
---

# skill-create

Scaffolds a new skill folder that already conforms to `SKILL_FRAMEWORK.md`, from a declared set of metadata. Can also audit an existing skill against the current standards and report what's out of date.

**When to invoke (create mode):** the user wants to create, build, or scaffold a new skill.

**What create mode produces:** a new folder at `/skills/<name>/` containing `skill.json`, the correct logic file for the declared stack (or none), `README.md`, `SECURITY.md` (minimal "no trust boundary" template by default, flagged with a TODO to fill in the fuller shape if this skill actually crosses one), `SKILL.md`, and a `test.py` stub — a correctly-shaped starting point, not a finished skill.

Before running `main.py` in create mode, gather the required metadata conversationally: `name`, `version`, `category`, `layer`, `rank`, `description`, `inputs`, `outputs`, `dependencies`, `stack`, `runtime-independent`, `logging`. See `SKILL_FRAMEWORK.md`'s Skill Metadata table for what each field means, and `AUTONOMY_RANKS.md` for how to pick `rank`.

If `main.py` exits with code 2, it's telling you the declared `stack` has no logging bootstrap defined yet. Ask what that stack's logging convention should be (library/module, format, output destination), add it to `main.py`'s `STACK_LOGGING_BOOTSTRAP` and to `SKILL_FRAMEWORK.md`'s Logging Standard in the same change, then retry — don't silently pass `--allow-missing-logging-bootstrap` on the user's behalf; that's their explicit call to defer.

**When to invoke (update mode):** the user wants an existing skill updated, audited, cleaned up, or brought in line with current standards.

**What update mode produces:** a read-only report (`python3 main.py --audit <skill-name>`) listing what's stale, ok, or needs manual review — it never rewrites a file itself. Fix flagged items conversationally, one file at a time, then re-run the audit to confirm.

## Documentation pass

Once `main.py` succeeds (create mode scaffolded cleanly, or update mode's flagged items have all been fixed and a re-audit comes back clean), run this pass before considering the invocation done. It's conversational — none of it is `main.py`'s job.

1. **Framework doc gap check.** State explicitly whether this skill's creation or change revealed a gap in `SKILL_FRAMEWORK.md`, `DEFINITION_OF_DONE.md`, `WORKFLOW.md`, or `COWORK_PROMPT.md`. If yes, fix it in the same change, per the same-PR doc-fix rule in `DEFINITION_OF_DONE.md`. Always state a conclusion, even "no gap found" — this check doesn't get silently skipped.
2. **Cross-skill impact check.** State explicitly whether this skill changes how another existing skill works, is invoked, or escalates to/from it. If yes, name the affected skill(s) and update their `README.md`/`SKILL.md` in the same change. Always state a conclusion, even "no other skill is affected."
3. **Skills Library Notion entry.** Draft the skill's Notion subpage using the "Skills Library Entry (Notion)" template in `SKILL_FRAMEWORK.md`, generated from the skill's current `README.md` and `skill.json` — don't write anything yet. Show the drafted content to the user and get explicit confirmation before creating or updating the actual Notion page. On confirmation: create mode gets a new subpage under the Skills Library index, titled with the skill's name; update mode updates that skill's existing subpage to match (or creates one if it never had one). Notion writes are a shared, durable surface, unlike the local files `main.py` writes directly — that's why this step waits for confirmation instead of writing automatically.

See `README.md` for full detail on how this skill works and what it depends on.
