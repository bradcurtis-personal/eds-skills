# prompt-creator

**Category:** Craft skill · **Rank:** 1 · **Layer:** Design

## What it does

Acts as a prompt engineer: when the user asks to write, draft or tidy a prompt for a Claude Code session, a Cowork session or a run of sequential subagents, reads the current session for context, asks only about gaps in one batch, and produces a short prompt tuned to the target.

## How to invoke it

Ask Claude Code or Cowork to write, draft or tidy a prompt for another session, for example "write a prompt for a Code session to work EDS-51" or "draft a prompt that runs three tickets as subagents". The skill:

1. Reads the session for goal, ticket keys, repos, constraints and decisions, and does not ask for what it already has.
2. Asks about any gaps in one batch (AskUserQuestion where available), or says nothing is missing.
3. Works out the target and tunes the prompt. Code gets a short prompt that points at the ticket and says "follow Ticket Workflow". Cowork gets connectors and the Cowork Session Prompt. Subagents get one ticket each, in order, with a stop condition and a report format.
4. Drafts the prompt: tickets named by key, the relevant hard limits, what done looks like and when to stop, and nothing repeated from `CLAUDE.md` or Ticket Workflow.
5. Checks the draft against a short list (ticket named not restated, hard limits, stop condition, no duplication, no credentials or invented branch types) and fixes failures.
6. Outputs the prompt in a code block, and posts it as a Jira comment when a ticket exists. With no ticket it asks whether to create one and posts nothing.

`SKILL.md` carries the full instructions and works on its own, because the installed plugin cannot be relied on to ship anything else.

## What it produces

One prompt in a code block, tuned to the target. When a Jira ticket exists, the same prompt posted as a comment on it. Protocol: conversational text, plus a Jira comment.

## Structure

| File | Purpose |
|---|---|
| `skill.json` | Metadata |
| `README.md` | This file |
| `SECURITY.md` | This skill's trust boundary -- see SKILL_FRAMEWORK.md's SECURITY.md section |
| `test.py` | Acceptance/contract test |
| `SKILL.md` | Cowork-invocable packaging of this skill |

## Dependencies

- Jira connector (only to post the prompt as a ticket comment)

## Version history

- **1.0.0** — Initial build.
