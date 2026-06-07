---
name: Debug (reproduce -> isolate -> fix)
description: Systematically diagnose and fix a bug instead of guessing.
triggers: [debug, fix bug, why does this fail, investigate error]
---

# Debug (reproduce -> isolate -> fix)

Use this to track down a bug methodically.

## Steps

1. **Reproduce.** Get a reliable, minimal repro. If you can't reproduce it, gather the
   exact error, stack trace, inputs, and environment first.
2. **Isolate.** Narrow the failure: read the stack trace, add targeted logging, bisect the
   input or the recent changes. Form a hypothesis about the root cause.
3. **Confirm root cause.** Verify the hypothesis — don't fix symptoms. State *why* it fails.
4. **Fix.** Apply the smallest change that addresses the root cause. Avoid unrelated edits.
5. **Verify + guard.** Re-run the repro to confirm the fix, run the broader tests for
   regressions, and add a test that would have caught this bug.

## Notes

- Resist guess-and-check. One confirmed root cause beats five speculative edits.
- Remove temporary logging/instrumentation before finishing.
