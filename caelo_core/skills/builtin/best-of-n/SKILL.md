---
name: Best of N (parallel attempts)
description: Delegate N parallel subagents on the same task, then pick the best result.
triggers: [best of n, parallel attempts, explore options, try variants, best-of-n]
---

# Best of N (parallel attempts)

Use this when a task has a wide solution space and you want the strongest result: run N
independent attempts in parallel and choose the best. Each attempt is isolated, so they
cannot interfere with each other.

## Steps

1. **Pick N.** Default N = 3 (cap to the parallelism limit). For a code task use the
   `implementer` role; for analysis/design use `researcher` or `design-doc-writer`.
2. **Fan out.** `delegate` N subagents with the **same** task in a single `delegate`
   call so they run in parallel. Give each identical, complete instructions.
3. **Compare.** When the summaries return, evaluate each against the goal and the
   acceptance criteria (correctness, simplicity, completeness, risk).
4. **Choose.** Pick the best attempt. The others' isolated copies are simply rejected at
   merge time (not applied).
5. **Summarize.** State which attempt you chose and why, and what is staged for merge.

## Notes

- The attempts are blind to each other — that is the point (diversity).
- Vary the instruction slightly per attempt only if you want different angles; otherwise
  keep them identical for a fair comparison.
- Only the chosen attempt's changes should be merged; explicitly discard the rest.
