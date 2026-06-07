---
name: Write tests
description: Add focused, meaningful tests for code — happy path plus the edge cases that matter.
triggers: [write tests, add tests, unit test, test coverage]
---

# Write tests

Use this when code needs tests. Aim for tests that would actually catch a regression,
not just raise the coverage number.

## Steps

1. **Locate the harness.** Find how tests are run and structured (test dir, framework,
   naming). Match it — do not introduce a new framework.
2. **Identify behavior.** List the function/module's contracts: expected output, error
   cases, boundaries (empty, null, large, malformed input).
3. **Write tests.** One assertion-focused test per behavior. Cover the happy path first,
   then the edge cases you listed. Name each test after the behavior it pins.
4. **Run them.** Execute the suite. Confirm the new tests pass and that they *fail* if you
   break the code (a test that can't fail is worthless).
5. **Report.** Summarize what is now covered and any behavior you deliberately left untested.

## Notes

- Prefer real assertions over snapshot dumps. Keep each test independent.
- Test behavior, not implementation details — so refactors don't break the tests.
