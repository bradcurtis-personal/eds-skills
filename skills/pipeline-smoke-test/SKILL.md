---
name: pipeline-smoke-test
description: Test fixture for the eds-skills pipeline that prints a greeting with a UTC timestamp and does nothing else.
---

# pipeline-smoke-test

Test fixture for the eds-skills pipeline that prints a greeting with a UTC timestamp and does nothing else. It exists only so the create > ship > install > document pipeline has something harmless to carry.

**When to invoke:** the user asks to run the pipeline smoke test, or to confirm that the `pipeline-smoke-test` plugin installed correctly.

**What it produces:** One line of text: `Hello from pipeline-smoke-test at <ISO-8601 UTC timestamp>`. In the `eds-skills` repo, run `python3 skills/pipeline-smoke-test/main.py` to print it. Where `main.py` isn't available (an installed plugin ships only this file), reply with that line yourself using the current UTC time.

See `README.md` for full detail on how this skill works and what it depends on.
