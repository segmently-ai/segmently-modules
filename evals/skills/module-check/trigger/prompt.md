---
description: A request that module-check should handle
tags: [trigger, core]
max_turns: 30
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Agent, Bash, Write, Edit]
---

Here is my plan for the catalog change: in `src/catalog/service.py` I will cache every book lookup in a module-level dict and write the price back as a float. Before I start, check the plan against the catalog module's rules and tell me what it breaks.
