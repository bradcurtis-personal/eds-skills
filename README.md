# eds-skills

Skill library for the Engineering Design System. See the `engineering-design-system` repo for the governing framework documents (`SKILL_FRAMEWORK.md` in particular defines the structure every skill here must follow).

Each skill lives in its own folder under `/skills/`:
- `skill.json` — metadata
- a logic file, if the skill's stack calls for one (e.g. `main.py`) — not every skill has one; see `SKILL_FRAMEWORK.md`'s "Physical Structure" section
- `README.md` — what it does, how to invoke it
- `test.py` — acceptance test
- `SKILL.md` — hand-authored or generated instructions used to package the skill for Cowork

## Deployment pipeline

Every skill is packaged and released independently. On every PR touching `skills/**`, `.github/workflows/skill-pr-check.yml` requires that skill's `skill.json` version to be bumped and runs its `test.py`. On merge to `main`, `.github/workflows/skill-release.yml` packages any skill with an unreleased version into its own plugin, publishes a GitHub Release (tag `<skill-name>/v<version>`) with the packaged `.plugin` file attached, and opens a PR to sync `.claude-plugin/marketplace.json` / `plugins/` so the skill is picked up by the org's GitHub-synced plugin marketplace in Cowork.

Both workflows call the shared engine in `tooling/package_skill.py`, which can also be run locally (needs `GITHUB_TOKEN` in `.env` — copy `.env.example`).
