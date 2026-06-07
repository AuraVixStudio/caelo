---
name: Review changes (multi-agent)
description: Delegate read-only reviewers over the local changes/branch and consolidate findings.
triggers: [review, code review, review changes, review diff, review branch]
---

# Review changes (multi-agent)

Use this to get a thorough, read-only review of the current local changes (or a branch)
by fanning out to `reviewer` subagents. Reviewers do not modify anything.

## Steps

1. **Scope the diff.** Identify what changed: run `git status` / `git diff --stat` (or
   `git diff <base>...HEAD`) with `run_command`, or `glob`/`list_dir` if there is no git.
   Build the list of changed files and group them by area.
2. **Delegate reviewers.** `delegate` a `reviewer` per area (parallel for independent
   areas). Tell each reviewer the exact files to read and the relevant changed lines, and
   ask for correctness bugs, security issues, and quality/maintainability concerns — each
   with a `file:line` reference and a short rationale.
3. **Consolidate.** Merge the returned findings, drop duplicates, and sort by severity.
4. **Report.** Present one prioritized list to the user. Do not fix anything here — this
   skill only reviews. (If the user wants fixes, switch to the `implement` loop.)

## Notes

- Reviewers are READONLY (no `run_command`); gather any command output (e.g. the diff)
  yourself and pass the relevant context into each subagent's task.
- Keep each reviewer's scope tight so its summary stays actionable.
