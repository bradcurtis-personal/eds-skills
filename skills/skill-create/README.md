# skill-create

**Category:** Meta skill · **Rank:** 1 · **Layer:** Design (meta-skills are always Design)

## What it does

Operates in one of two modes, auto-selected by whether the target skill already exists:

**Create mode** — scaffolds a new skill folder under `/skills/` that already conforms to `SKILL_FRAMEWORK.md`: correct structure, all required `skill.json` metadata fields present and validated, naming convention enforced, the correct logic file chosen for the declared `stack` (or no logic file, for an instruction-only skill), a generated `README.md`, a generated `SECURITY.md` (the minimal "no trust boundary" template by default, flagged with a TODO to fill in the fuller shape if the skill actually crosses one), a generated `SKILL.md` (content depth matched to the skill's category), and a `test.py` stub pre-filled with the declared inputs/outputs.

**Update mode** — audits an existing skill against the *current* `SKILL_FRAMEWORK.md` rules and reports what's stale: missing/invalid `skill.json` fields, a logic file that no longer matches the declared stack (wrong name, or a leftover file from a stack that was since changed), a missing `SKILL.md`/`README.md`/`SECURITY.md`/`test.py`, and a note to manually re-check `SKILL.md`'s content depth against its category. Update mode is **audit + report only** — it never rewrites a content-bearing file itself. Findings are meant to be fixed conversationally, one file at a time, by a human or Claude, then re-audited to confirm. It always targets exactly one named skill; there is no bulk "audit everything" sweep.

`main.py` does the deterministic work in both modes. Gathering create-mode metadata from whoever's building the skill — asking for `name`, `version`, `category`, `layer`, `rank`, `description`, `inputs`, `outputs`, `dependencies`, `stack`, `runtime-independent`, and `logging` — is Cowork's job, per `SKILL.md`'s instructions, before `main.py` ever runs.

## How to invoke it

To create a new skill, ask to create/build/scaffold it. Cowork gathers the required metadata conversationally, then runs:

```
python3 skills/skill-create/main.py --metadata '{"name": "arduino-sketch", ...}'
```

or with a metadata file:

```
python3 skills/skill-create/main.py --metadata-file metadata.json
```

To update or clean up an existing skill, ask to update/audit/clean up that skill by name. Cowork runs:

```
python3 skills/skill-create/main.py --audit arduino-sketch
```

which prints a checklist of what's stale, ok, or needs manual review, and exits non-zero if anything is stale. Nothing on disk changes.

Either mode ends with a documentation pass, not just a finished folder — see "Documentation pass" below.

## Documentation pass

`main.py` only ever touches the local filesystem. Once it succeeds — a clean scaffold, or an update-mode re-audit that comes back clean — Cowork runs this pass conversationally, per `SKILL.md`'s instructions, before the invocation is considered done:

1. **Framework doc gap check** — does this skill's creation or change reveal a gap in `SKILL_FRAMEWORK.md`, `DEFINITION_OF_DONE.md`, `WORKFLOW.md`, or `COWORK_PROMPT.md`? Fixed in the same change if so, per the same-PR doc-fix rule. A conclusion is always stated, even "no gap found."
2. **Cross-skill impact check** — does this skill change how another existing skill works, is invoked, or escalates to/from it? Affected skills' `README.md`/`SKILL.md` get updated in the same change if so. A conclusion is always stated, even "no other skill affected."
3. **Skills Library Notion entry** — drafted from the skill's `README.md` and `skill.json` using `SKILL_FRAMEWORK.md`'s "Skills Library Entry (Notion)" template, shown to the user, and only written to Notion (new subpage for create mode, updated existing subpage for update mode) after explicit confirmation. Notion is a shared, durable surface, unlike the files `main.py` writes locally — that's the reason this step isn't automatic the way local file writes are.

## Logging bootstrap resolution

When create mode hits a `stack` that has no logging bootstrap defined yet in `STACK_LOGGING_BOOTSTRAP`, `main.py` refuses to scaffold (exit code 2) rather than silently writing a `TODO` stub. Nothing partial is left behind. Cowork should treat that as a prompt to resolve the gap right there: ask what logging convention this stack should use (library/module, format, output destination), add a template to `main.py`'s `STACK_LOGGING_BOOTSTRAP`, and document the convention in `SKILL_FRAMEWORK.md`'s Logging Standard — in the same change, per the same-PR doc-fix rule in `DEFINITION_OF_DONE.md` — then retry. If that conversation genuinely needs to be deferred, `--allow-missing-logging-bootstrap` scaffolds with the old `TODO` stub instead, as a deliberate, explicit exception rather than the default path.

## What it produces

A new folder at `/skills/<name>/` containing:

| File | Always present? |
|---|---|
| `skill.json` | Always |
| the logic file (name depends on `stack` — see `SKILL_FRAMEWORK.md`'s "Logic file naming by stack") | Only when the stack calls for one |
| `README.md` | Always (scaffold — needs real content filled in) |
| `SECURITY.md` | Always (scaffold — minimal template by default; fill in the fuller shape if this skill crosses a real trust boundary) |
| `SKILL.md` | Always (scaffold — content depth depends on category) |
| `test.py` | Always (scaffold — needs real assertions filled in) |

None of this is the finished skill. `skill-create` gets a new skill to a correctly-shaped, non-broken starting point — the real logic, real documentation, and real contract test still have to be written before the Definition of Done sequence can pass.

## Structure

| File | Purpose |
|---|---|
| `skill.json` | Metadata |
| `main.py` | This skill's logic — the scaffolding engine |
| `README.md` | This file |
| `SECURITY.md` | This skill's trust boundary — see `SKILL_FRAMEWORK.md`'s `SECURITY.md` section |
| `test.py` | Contract test — verifies `skill-create` scaffolds a sample skill correctly, against a disposable temp directory (never the real `/skills/` library) |
| `SKILL.md` | Cowork-invocable packaging of this skill |

## Dependencies

None — `skill-create` only touches the local filesystem.

## Known limits (v1.1.0)

- The stack→logic-file lookup table only knows Python, Node.js, Arduino C++, and instruction-only. An unrecognized stack fails loudly rather than guessing — add a row to `main.py`'s `STACK_LOGIC_FILE` and to `SKILL_FRAMEWORK.md` before scaffolding a new stack.
- Only Python has a logging bootstrap defined in `STACK_LOGGING_BOOTSTRAP`. Scaffolding any other stack for the first time blocks and asks for that stack's logging convention to be resolved (see "Logging bootstrap resolution" above) rather than silently guessing or stubbing.
- Update mode's `SKILL.md` content-depth check is a note, not an assertion — it can't be verified mechanically, so it always asks for a manual look.
- Update mode's README audit checks that the fixed section headers are present, not that their content is accurate or current — that's still a human/Claude judgment call.
- The documentation pass's two checklist items (framework doc gaps, cross-skill impact) are conversational judgment calls stated by Cowork, not something `main.py` or `test.py` can verify mechanically.
- `skill-create` does not commit, push, or open a PR — those stay manual steps per `WORKFLOW.md`, same as every other skill.
- `SECURITY.md` is always scaffolded with the minimal "no trust boundary" template plus a TODO — `main.py` has no way to know whether a skill actually crosses a trust boundary, so choosing between the minimal and fuller shape (per `SKILL_FRAMEWORK.md`'s `SECURITY.md` section) stays a human/Claude judgment call, same as `SKILL.md`'s content depth.

## Version history

- **1.1.0** (EDS-7) — Scaffolds and audits `SECURITY.md` for every skill, per `SKILL_FRAMEWORK.md`'s Physical Structure requirement (added in EDS-6): minimal "no trust boundary" template with a TODO by default, flagged as stale by the audit when missing.
- **1.0.0** (EDS-3) — Initial build: create mode, update/audit mode, logging-bootstrap resolution (block by default with an explicit override), README's fixed section order (including Version history) enforced by both the scaffold and the audit, and a documentation pass (framework doc gap check, cross-skill impact check, Skills Library Notion entry drafted and confirmed before writing).
