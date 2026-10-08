# Security

**Trust boundary:** Minimal. This skill is instruction-only (no logic file, no scripts). It reads the current session's context and writes a prompt as text. Its one external write is a comment on a Jira ticket, made through the user's own Jira connector, and only when a ticket exists.

## What this skill touches

- The current conversation (read).
- One Jira comment on the named ticket (write), via the connector the session already has.

## Why that's safe

- It never posts without a ticket, and never creates a ticket without asking.
- It writes no files, runs no commands, and opens no ports.
- Its self-check refuses prompts that contain credentials or tokens.
- Generated prompts carry the standing hard limits (merges stay with Brad, workflow-file diff review, Notion drafts shown first) rather than loosening them.

## Out of scope

Whether the prompt it writes is a good idea to run, and what the target session does with it. No high-leverage files.
