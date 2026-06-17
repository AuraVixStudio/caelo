---
name: Review a GitHub PR (via gh)
description: Review a specific GitHub pull request with gh — fetch the diff, fan out reviewers, consolidate, and optionally post the review. Requires the `gh` CLI or the GitHub MCP server.
triggers: [pr review, review pr, github pr, gh pr, pull request review]
---

# Review a GitHub PR (via gh)

Use this to review a specific GitHub pull request thoroughly and — only if asked — post the
review back to GitHub. (For a review of the *local* changes, use the `review` skill; to drive a
PR to green CI, use `pr-babysit`.)

> **Dependency:** needs the `gh` CLI installed + authenticated (run `gh auth login`), or the
> GitHub MCP server enabled. If neither is available, tell the user and stop. Note: `run_command`
> runs with a scrubbed environment, so env tokens like `GH_TOKEN`/`GITHUB_TOKEN` are stripped —
> `gh` must be authenticated via `gh auth login` (its config/keyring), not an env var.

## Steps

1. **Fetch the PR.** With `run_command`: `gh pr view <n> --json
   title,body,headRefName,baseRefName,files` and `gh pr diff <n>` (or the GitHub MCP tools).
   Identify the changed files and group them by area.
2. **Delegate reviewers.** `delegate` a `reviewer` per area (parallel for independent areas). Give
   each reviewer the exact files plus the relevant diff hunks, and ask for correctness bugs,
   security issues, and quality/maintainability concerns — each with a `file:line` reference and a
   short rationale. Reviewers are READONLY (no `run_command`).
3. **Consolidate.** Merge the returned findings, drop duplicates, and sort by severity.
4. **Report.** Present one prioritized list (most severe first) to the user.
5. **Post (only if asked).** If the user explicitly wants the review posted, use
   `gh pr review <n> --comment` (or `--request-changes` / `--approve`) with the consolidated
   summary as the body. This is a MUTATION and goes through approval. Do NOT merge or close the PR.

## Notes

- Reviewers do not run commands — gather the `gh pr diff` output yourself and pass the relevant
  hunks into each subagent's task.
- Keep each reviewer's scope tight so its summary stays concrete and actionable.
- Never post to GitHub without an explicit request from the user.
