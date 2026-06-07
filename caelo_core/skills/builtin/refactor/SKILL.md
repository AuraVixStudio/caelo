---
name: Refactor (behavior-preserving)
description: Improve code structure in small, safe steps without changing behavior.
triggers: [refactor, clean up, simplify, restructure]
---

# Refactor (behavior-preserving)

Use this to improve readability/structure without changing what the code does.

## Steps

1. **Pin behavior.** Make sure there are tests (or add a couple) that capture the current
   behavior before you touch anything.
2. **Small steps.** Make one structural change at a time (extract function, rename, dedup,
   inline). Keep each step mechanical and reversible.
3. **Verify each step.** Run tests / type-check after each change. Never batch many
   refactors and verify once at the end.
4. **No behavior change.** If you spot a bug, note it and fix it in a *separate* change —
   not inside the refactor.
5. **Report.** Summarize the structural changes and confirm behavior is unchanged.

## Notes

- Match the surrounding style and naming. The diff should read as obviously equivalent.
- Stop when the code is clear — refactoring has diminishing returns.
