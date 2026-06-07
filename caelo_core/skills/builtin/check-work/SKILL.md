---
name: Check work (verify against criteria)
description: Verify an implementation against acceptance criteria with a reviewer and a tester.
triggers: [check work, verify, acceptance criteria, definition of done, validate]
---

# Check work (verify against criteria)

Use this after a change to confirm it actually meets the stated acceptance criteria,
combining a read-only `reviewer` with a `tester` that runs the suite in an isolated copy.

## Steps

1. **Restate criteria.** Write down the explicit acceptance criteria / definition of done
   for the change (ask the user if they are unclear).
2. **Review.** `delegate` a `reviewer` to check the changes against each criterion and
   flag anything unmet, with `file:line` references.
3. **Test.** `delegate` a `tester` to run the relevant tests/build with `run_command` and
   report pass/fail with the actionable failures.
4. **Decide.** Report **PASS** only if the reviewer finds every criterion met AND the
   tester is green. Otherwise list exactly what fails.
5. **(Optional) Fix.** If the user wants it closed out, hand the failures to the
   `implement` loop; otherwise stop at the verdict.

## Notes

- The reviewer is READONLY; the tester runs in an isolated worktree (its changes, if any,
  await merge review).
- Be explicit and binary in the final verdict — PASS or a concrete list of gaps.
