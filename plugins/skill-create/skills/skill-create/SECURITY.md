# Security

**Trust boundary:** None -- this skill reads its declared inputs and writes only its own generated output files (new skill folders under `/skills/<name>/`). It does not mutate shared config, execute arbitrary code, open network ports, or cross any other trust boundary.

The one action that touches a shared, durable surface -- writing a skill's entry to Notion during the documentation pass -- happens conversationally, outside `main.py`, only after explicit user confirmation of the drafted content (see README.md's "Documentation pass" section). `main.py` itself never reaches outside the local filesystem.
