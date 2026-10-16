# The rule check

Give the checking agent this text, the rules file and the plan (or the diff) in place of the
two placeholders, and nothing else: no tools, no other docs.

```text
You check a plan for a code change against the repository's rules for the modules it touches.

## Rules
<the output of segmently-modules rules>

## The plan
<the plan, the design or the report; or the diff>

Return two lists.
1. conflicts — the plan's own words prescribe, or clearly lead to, what a rule forbids. Quote the
   plan's words; no quote, no conflict. A rule the plan merely does not mention is never a
   conflict.
2. reminders — at most 5 rules that clearly apply to the files or the approach this plan names,
   that the plan does not mention, and that would cause real damage if forgotten. Not general
   good practice.
Reply with only JSON: {"conflicts": [{"rule": "...", "source": "<doc>:<line>", "plan_quote": "...",
"fix": "..."}], "reminders": [{"rule": "...", "source": "<doc>:<line>", "why": "..."}]}
```

Report its answer as the skill's `Report` says. A conflict whose quote is not in the plan is
dropped: the check names only what the plan says.
