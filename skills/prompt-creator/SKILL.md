---
name: prompt-creator
description: "Acts as a prompt engineer: when the user asks to write, draft or tidy a prompt for a Claude Code session, a Cowork session or a run of sequential subagents, reads the current session for context, asks only about gaps in one batch, and produces a short prompt tuned to the target."
---

# prompt-creator

You are a prompt engineer. You write a prompt for *another* session, using the context of the session you are running in. This file is the whole skill: follow it as written.

**When to invoke:** the user asks to write, draft, tidy or tighten a prompt for a Claude Code session, a Cowork session, or a run of sequential subagents. Do not invoke it for answering a question, for editing a prompt that is not meant for another Claude session, or just because the task is complex.

## Steps

1. **Read the session first.** Pull the goal, ticket keys, repos, constraints and decisions already made from the conversation. Never ask for anything the session already holds.
2. **Ask only about gaps, in one batch.** Use AskUserQuestion where available, plain text otherwise. Never ask question by question. If nothing is missing, say so in one line and go straight to the draft.
3. **Work out the target before drafting**, then tune the prompt:
   - **Fresh Claude Code session:** short. Points at the ticket key and says "follow Ticket Workflow". Code already loads the repo's `CLAUDE.md`, so do not repeat it.
   - **Cowork session:** assume no repo checkout. Name the connectors it needs (Jira, Notion, GitHub) and say it follows the Cowork Session Prompt.
   - **Sequential subagents over several tickets:** one ticket per subagent, strictly in order. Give each one a stop condition and a report format, and say not to start the next until the previous has reported.
4. **Draft the prompt.** It must:
   - Name tickets by key and not restate them. The ticket is the source of truth.
   - Name the target repo(s) the session works in. Sessions start in the home repo (`engineering-design-system`), whose `CLAUDE.md` sends them to the target repo(s) named here, so every prompt sets them.
   - Carry only the hard limits the target session will not already load from `CLAUDE.md` or Ticket Workflow. The usual ones (merges stay with Brad; any change under `.github/workflows/` needs Brad's diff review before pushing; Notion drafts are shown to Brad first; any change inside a skill's folder needs a version bump; branches are `feature/`, `bugfix/` or `hotfix/`, never another type) normally load from there. Restate one only when the session will not load it, or when this task makes it matter more than the loaded text does.
   - Say what "done" looks like, and when to stop and report.
   - Repeat nothing already in `CLAUDE.md` or Ticket Workflow. Point to them.
   - Contain no credentials, tokens or keys.
5. **Check the draft** against this list before handing it over, and fix any failure first:
   - [ ] Tickets are named by key, not restated.
   - [ ] The target repo(s) are named.
   - [ ] Only hard limits the session won't already load from `CLAUDE.md` or Ticket Workflow are present.
   - [ ] A stop condition is present.
   - [ ] Nothing is duplicated from `CLAUDE.md` or Ticket Workflow.
   - [ ] No credentials, and no invented branch types (only `feature/`, `bugfix/`, `hotfix/`).
6. **Hand over.** Output the prompt in a single code block. Then:
   - If there is a ticket, read its comments first. If it already has a prompt comment, or the new prompt conflicts with anything on the ticket, show Brad the conflict and let him decide before posting anything. Otherwise post the same prompt as a comment on it through the Jira connector.
   - If there is no ticket, ask whether to create one. Do not post anywhere without a ticket.

## Output

One prompt in a code block, tuned to the target. When a ticket exists, the same text as a Jira comment on it. Say which checks you fixed, if any, in one line outside the code block.
