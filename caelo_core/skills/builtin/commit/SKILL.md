---
name: Commit (clean, conventional)
description: Stage the right changes and write a clear, conventional commit message.
triggers: [commit, git commit, write commit message]
---

# Commit (clean, conventional)

Use this when the user asks to commit work. Produce a focused commit with a message
that explains *why*, not just *what*.

## Steps

1. **Review.** Run `git status` and `git diff` (and `git diff --staged`) to see exactly
   what changed. Read the changes — do not commit blind.
2. **Scope.** Stage only the related changes for one logical commit. If the diff mixes
   unrelated work, make separate commits. Never `git add -A` without checking what it picks up.
3. **Message.** Write a Conventional-Commits subject (`type(scope): summary`, <=72 chars):
   `feat` / `fix` / `refactor` / `docs` / `test` / `chore`. Add a body explaining the
   reason and any trade-offs when the change is non-trivial.
4. **Verify.** Re-read the staged diff before committing. Do not commit secrets, debug
   prints, or unrelated files.
5. **Commit.** Create the commit and report the subject line back. Push only if the user
   explicitly asked.

## Notes

- Match the repository's existing commit style if it differs from Conventional Commits.
- One commit = one reviewable idea.
