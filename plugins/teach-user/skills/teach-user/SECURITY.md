# Security

**Trust boundary:** None -- this is a system skill with no logic file (`SKILL.md`'s body *is* its logic, per SKILL_FRAMEWORK.md). It changes Cowork's conversational behavior for the duration of its invocation and logs a cleaned-up explanation to Notion; it does not mutate shared config, execute arbitrary code, open network ports, or handle another tool's data.
