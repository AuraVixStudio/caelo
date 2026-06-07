---
name: PR babysit (watch & drive to green)
description: Watch a pull request and delegate fixes until CI is green and reviews are addressed. Requires the GitHub MCP server or `gh`.
triggers: [pr babysit, watch pr, pull request, ci green, pr-babysit]
---

# PR babysit (watch & drive to green)

Use this to shepherd a pull request to a mergeable state: monitor checks and review
comments, and delegate fixes as needed.

> **Dependency:** this skill needs read access to the PR — either the **GitHub MCP
> server** enabled, or the `gh` CLI available to the `tester`/`run_command` tool. If
> neither is configured, tell the user and stop.

## Loop

1. **Fetch status.** Get the PR's CI checks, mergeability, and review comments via the
   GitHub MCP tools, or `gh pr view <n> --json ...` / `gh pr checks <n>` through
   `run_command`.
2. **Triage.**
   - CI failing -> `delegate` a `tester` (or `implementer`) to reproduce, diagnose, and fix.
   - Changes requested in review -> `delegate` an `implementer` to address each comment.
   - Green + approved -> you are done.
3. **Re-check.** After fixes are merged in, fetch status again.
4. **Repeat** steps 1–3 until the PR is green and approved, or you hit the round limit.
5. **Summarize.** Report the final PR state and what was changed.

## Notes

- Do not merge or close the PR yourself — surface the green/approved state and let the
  user merge.
- Keep polling bounded (respect the round/turn limits); report progress between rounds.
