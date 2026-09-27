---
description: A request that module-discover should handle
tags: [trigger, core]
max_turns: 30
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Bash, Write, Edit]
---

The task is agreed: when a book is added to the catalog, validate its ISBN-13 check digit, and show a clear message in the cart when a book with an invalid ISBN is in it. Which modules, docs and code files will this touch? Do not change anything yet.
