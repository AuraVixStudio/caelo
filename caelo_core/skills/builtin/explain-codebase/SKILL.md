---
name: Explain codebase
description: Map and explain an unfamiliar codebase or module to the user.
triggers: [explain, how does this work, walk me through, understand codebase, onboarding]
---

# Explain codebase

Use this when the user wants to understand how a project or module works.

## Steps

1. **Orient.** Find the entry points, the build/run commands, and any README/architecture
   docs. Identify the main directories and what each is responsible for.
2. **Trace a path.** Pick a representative flow (a request, a command, a feature) and
   follow it across files. Concrete paths explain a system better than abstractions.
3. **Map the pieces.** Note the key modules, the data model, and how components talk to
   each other (calls, events, HTTP, queues).
4. **Explain.** Summarize for the user: the big picture first, then the important
   components, then the one flow you traced — with clickable `file:line` references.
5. **Point forward.** Call out where to look to change X, and any sharp edges or
   conventions worth knowing.

## Notes

- Read before asserting. Verify names/paths exist rather than inferring from memory.
- Tailor depth to the user's question — don't dump the whole tree.
