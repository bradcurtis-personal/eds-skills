# skill-create

**Category:** Meta skill · **Rank:** 1 · **Layer:** Design (meta-skills are always Design)

## What it does

Operates in one of two modes, auto-selected by whether the target skill already exists:

**Create mode** — scaffolds a new skill folder under `/skills/` that already conforms to `SKILL_FRAMEWORK.md`: correct structure, all required `skill.json` metadata fields present and validated, naming convention enforced, the correct logic file chosen for the declared `stack` (or no logic file, for an instruction-only skill), a generated `README.md`, a generated `SECURITY.md` (the minimal "no trust boundary" template by default, flagged with a TODO to fill in the fuller shape if the skill actually crosses one), a generated `SKILL.md` (content depth matched to the skill's category), and a `test.py` stub pre-filled with the declared inputs/outputs.

**Update mode** — audits an existing skill against the *current* `SKILL_FRAMEWORK.md` rules and reports what's stale: missing/invalid `skill.json` fields, a logic file that no longer matches the declared stack (wrong name, or a leftover file from a stack that was since changed), a missing `SKILL.md`/`README.md`/`SECURITY.md`/`test.py`, a `README.md` missing any of its required section headers, a file in the skill folder that the README's Structure table does not list, a `SKILL.md` whose frontmatter does not parse as YAML or has no non-empty description, leftover scaffold placeholders (reported as stale), a Python `main.py` whose logging bootstrap opens `logs/...` without creating the directory (stale) or adds a handler without a `.handlers` guard (a note), and a note to manually re-check `SKILL.md`'s content depth against its category. It exits non-zero on anything stale, and the PR gate (`package_skill.py check`) runs it on every changed skill. Update mode is **audit + report only** — it never rewrites a content-bearing file itself. Findings are meant to be fixed conversationally, one file at a time, by a human or Claude, then re-audited to confirm. It always targets exactly one named skill; there is no bulk "audit everything" sweep.

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

1. **Framework doc gap check** — does this skill's creation or change reveal a gap in `SKILL_FRAMEWORK.md`, `DEFINITION_OF_DONE.md` or `WORKFLOW.md` (in the `engineering-design-system` repo)? Fixed in the same change if so, per the same-PR doc-fix rule. If the gap is in the Cowork Session Prompt, which lives only in Notion, the Notion change is drafted for Brad's approval and the page re-read afterwards instead. A conclusion is always stated, even "no gap found."
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

`skill-create` itself only touches the local filesystem, and `main.py` (create mode and `--audit`) needs only the Python standard library: without PyYAML, `--audit` parses `SKILL.md` frontmatter with a stdlib fallback that handles plain, single-quoted and double-quoted single-line scalars (see "Known limits"), and it passes on every skill in the repo. PyYAML is still needed for `SKILL.md` frontmatter in the other YAML forms (block or multi-line values, flow collections and so on, which `--audit` otherwise reports as not parsing), and for the tests that check the frontmatter against real YAML: two tests in this skill's `test.py` (`test_description_with_colon_space_is_valid_yaml_and_round_trips` and `test_description_with_quotes_hash_backslash_newline_round_trips`) import `yaml`, and the YAML-equivalence checks of the fallback compare against it when it is installed. It is pinned in the repo's `requirements.txt`, which CI (`skill-pr-check`) installs; a local run of this skill's full `test.py` needs `python3 -m pip install -r requirements.txt`. See `SECURITY.md` and `skill.json`'s `dependencies`.

## Known limits

- The stack→logic-file lookup table only knows Python, Node.js, Arduino C++, and instruction-only. An unrecognized stack fails loudly rather than guessing — add a row to `main.py`'s `STACK_LOGIC_FILE` and to `SKILL_FRAMEWORK.md` before scaffolding a new stack.
- Only Python has a logging bootstrap defined in `STACK_LOGGING_BOOTSTRAP`. Scaffolding any other stack for the first time blocks and asks for that stack's logging convention to be resolved (see "Logging bootstrap resolution" above) rather than silently guessing or stubbing.
- Update mode's `SKILL.md` content-depth check is a note, not an assertion — it can't be verified mechanically, so it always asks for a manual look.
- Update mode's leftover-placeholder check matches only the exact wording the scaffold generated. A placeholder someone reworded by hand, or a stub they wrote themselves, is not detected.
- Update mode's logging-bootstrap check is textual: it looks for a `FileHandler("logs/...")` and any `makedirs(`/`.mkdir(` call anywhere in `main.py` (not that the call runs before the handler), and for an `addHandler` call with no `.handlers` mention. Other bootstrap shapes are not inspected.
- Update mode parses `SKILL.md`'s frontmatter with `yaml.safe_load` when PyYAML is installed. Without PyYAML it uses a stdlib fallback that is a strict subset of YAML: a mapping of single-line `key: value` lines, where each value is a plain scalar (no `: ` or ` #` inside, not starting with a YAML indicator character such as `[ { & * ! | > ' " % @ - ? : , #`, not empty, and not something YAML reads as a number, boolean, null or date, such as `123`, `true`, `~` or `2026-10-08`), a single-quoted scalar (`''` for a quote, no backslash escapes), or a JSON-style double-quoted scalar (what the scaffold writes). Whenever the fallback accepts a value, `yaml.safe_load` returns the same string. Everything else is rejected with a message saying PyYAML is needed to parse that form: block (`|`, `>`) and multi-line or indented values, flow collections, anchors, aliases and tags, a trailing comment after a quoted scalar, YAML-only double-quote escapes (`\x41`, `\e`, ...), `\uD800`-`\uDFFF` surrogate escapes (which PyYAML decodes differently from JSON; the scaffold writes one for any character outside the Basic Multilingual Plane, such as an emoji), tabs and control characters. This is what lets the audit pass on every skill in the repo without PyYAML. The generated `test.py` has its own, still stricter fallback (double-quoted `description:` only), and the tests listed under "Dependencies" still need PyYAML. Tracked in EDS-39.
- Update mode's README audit checks that the fixed section headers are present, not that their content is accurate or current — that's still a human/Claude judgment call.
- Update mode's Structure-table check is textual: it reads the first column of the table rows under `## Structure` (the backticked names, or the bare text when there are none) and compares them with the regular files directly in the skill folder. A file the table omits is stale; a listed name with no such file is a note. Subfolders and dotfiles are ignored, and it does not check the Purpose column or any table outside that section.
- The documentation pass's two checklist items (framework doc gaps, cross-skill impact) are conversational judgment calls stated by Cowork, not something `main.py` or `test.py` can verify mechanically.
- `skill-create` does not commit, push, or open a PR — those stay manual steps per `WORKFLOW.md`, same as every other skill.
- `SECURITY.md` is always scaffolded with the minimal "no trust boundary" template plus a TODO — `main.py` has no way to know whether a skill actually crosses a trust boundary, so choosing between the minimal and fuller shape (per `SKILL_FRAMEWORK.md`'s `SECURITY.md` section) stays a human/Claude judgment call, same as `SKILL.md`'s content depth.

## Version history

- **1.4.0** (EDS-41) — `--audit` now compares the README's Structure table with the files in the skill folder: a file the table omits is reported as stale (non-zero exit, naming the file), and a table row for a file that does not exist is a "need manual review" note. The README is the source for the Skills Library entry, so an incomplete table used to produce an incomplete entry with nothing failing (teach-user's missing `SECURITY.md` row, fixed in teach-user 1.1.3, was the example). Minor bump because audit gained a check; every skill in the repo already passes. New tests drop a row and assert the audit names the file, add a row for a missing file, and check subfolders and dotfiles are ignored.
- **1.3.4** (EDS-39) — Fix: the stdlib frontmatter fallback (used when PyYAML is not installed) now accepts the single-line scalar shapes real `SKILL.md` files use: plain, single-quoted and JSON-style double-quoted `description:` values, instead of only the double-quoted shape the scaffold writes. Before, `--audit` exited 1 without PyYAML on `skill-create`'s own and `pipeline-smoke-test`'s `SKILL.md` (and `teach-user`'s). The fallback is a strict subset of YAML (anything it accepts, `yaml.safe_load` reads as the same string) and rejects every other form (block or multi-line values, flow collections, anchors, trailing comments after a quoted scalar, YAML-only escapes, values YAML reads as numbers, booleans, null or dates) with a message saying PyYAML is needed. No new check, so a patch bump; the scaffold still writes the description with `json.dumps`, and the PyYAML path is unchanged. New tests run `--audit` and the parser with `import yaml` blocked, over a table of accepted and rejected shapes compared with `yaml.safe_load`, and over every skill in `skills/`.
- **1.3.3** (EDS-34) — Documentation only: the README's "Known limits" section rewritten to match the current behaviour (audit wired into the PR gate, scaffold-marker and logging-bootstrap checks, YAML frontmatter parsing), plus the "Dependencies" section (PyYAML is needed by `test.py`, the audit and the PR gate) and the update-mode paragraph in "What it does" brought up to date with the checks `--audit` runs today. No behaviour change.
- **1.3.2** (EDS-30) — Wording fix, no behavior change: the documentation pass's framework doc gap check (`SKILL.md` and this README) no longer lists the Cowork Session Prompt's repo file, since the prompt now lives only in Notion (the repo file is a stub); the three remaining documents are named as living in the `engineering-design-system` repo, and a gap in the Cowork Session Prompt is handled by drafting the Notion change for Brad's approval and re-reading the page. No change to `main.py` or `test.py`.
- **1.3.1** (EDS-38) — Declares the PyYAML dependency that `test.py` has needed since 1.1.2: `skill.json`'s `dependencies` and `SECURITY.md` now name it (test/audit-time only; `main.py` uses a stricter stdlib frontmatter check without it), and the version is pinned in a repo-root `requirements.txt` (`pyyaml==6.0.3`) that `skill-pr-check` installs from instead of an unpinned `pip install pyyaml`. No change to `main.py`.
- **1.3.0** (EDS-37) — The generated Python logging bootstrap now guards `logger.addHandler(handler)` with `if not logger.handlers`, matching `skill-create`'s own `_make_logger`, so importing or reloading a scaffolded `main.py` twice in one process no longer duplicates every log line. `--audit` now inspects the Python logging bootstrap: a `FileHandler("logs/...")` with no `makedirs`/`mkdir` call anywhere in `main.py` (the pre-EDS-16 bootstrap, which crashes at import outside a folder that already has `logs/`) is reported as stale, and an `addHandler` call with no `.handlers` check is reported as a "need manual review" note, not stale, so existing skills without the guard keep passing the PR gate. Minor bump because audit gained a check. New tests import a scaffolded `main.py` twice and assert one handler, and audit an old-style bootstrap (stale) against a fresh one (clean).
- **1.2.0** (EDS-17) — `--audit` now reports leftover scaffold placeholders as stale (non-zero exit), listing each one: the generated `TODO` lines in `README.md`, `SKILL.md` (including the system-skill variants) and `SECURITY.md`, the scaffold `NotImplementedError` and `TODO: implement ...` line in the logic file, and the "scaffold-level only" message in `test.py`. Before this, an untouched scaffold passed both `test.py` and `--audit`, so the PR gate could not tell it from a finished skill. Only the audited skill's own files are scanned for the exact scaffold wording, so auditing `skill-create` itself (whose template source holds the same text) still reports 0 stale. Minor bump because audit behavior changed: a scaffold that used to audit clean now fails. `package_skill.py check` is not wired to `--audit` yet (see EDS-17). New tests scaffold a skill, assert the audit fails with the findings listed, fill in the markers, and assert it passes.
- **1.1.3** (EDS-16) — The generated Python logging bootstrap now runs `os.makedirs("logs", exist_ok=True)` before opening `logs/<skill>.log` (flat-file backend only), so a scaffolded `main.py` no longer crashes with `FileNotFoundError` at import when `logs/` is missing (fresh checkout, CI, another working directory). New test scaffolds a skill and runs its `main.py` from an empty working directory.
- **1.1.2** (EDS-15) — `build_skill_md()` now writes the description as a JSON-style double-quoted scalar, so descriptions containing `: `, `#`, quotes, backslashes or newlines produce valid YAML frontmatter (before, `: ` made it invalid YAML while the checks still passed). `--audit` and the generated `test.py` now parse the frontmatter as real YAML (`yaml.safe_load` when PyYAML is installed, otherwise a strict stdlib check of the double-quoted description) and require a non-empty string description (a description that differs from `skill.json`'s is reported as a note, since `SKILL.md` carries the trigger wording). `skill-pr-check` installs PyYAML so this skill's own test uses real YAML.
- **1.1.1** (EDS-13) — `SKILL.md` now says where `main.py` lives (the folder containing `SKILL.md`, which is the same relative location in the repo and in an installed plugin) and to pass `--output-dir` when running it from an installed plugin. The packaging pipeline (`tooling/package_skill.py`) now ships `main.py`, `README.md` and `SECURITY.md` inside the `.plugin` and `plugins/skill-create/`; before this, only `SKILL.md` shipped. No change to `main.py`.
- **1.1.0** (EDS-7) — Scaffolds and audits `SECURITY.md` for every skill, per `SKILL_FRAMEWORK.md`'s Physical Structure requirement (added in EDS-6): minimal "no trust boundary" template with a TODO by default, flagged as stale by the audit when missing.
- **1.0.0** (EDS-3) — Initial build: create mode, update/audit mode, logging-bootstrap resolution (block by default with an explicit override), README's fixed section order (including Version history) enforced by both the scaffold and the audit, and a documentation pass (framework doc gap check, cross-skill impact check, Skills Library Notion entry drafted and confirmed before writing).
