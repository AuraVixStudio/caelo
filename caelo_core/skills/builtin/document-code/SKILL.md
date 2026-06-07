---
name: Document code
description: Add clear docstrings/comments and update docs for changed or unfamiliar code.
triggers: [document, add docstrings, write docs, comment code]
---

# Document code

Use this to make code understandable to the next reader.

## Steps

1. **Understand first.** Read the code until you can explain what it does and why. Don't
   document guesses.
2. **Docstrings.** Add/update docstrings on public functions, classes and modules:
   purpose, parameters, return value, and non-obvious behavior or side effects. Match the
   project's docstring style.
3. **Comments where they earn their place.** Explain *why* (intent, trade-offs, gotchas),
   not *what* the code already says. Remove stale comments.
4. **External docs.** If the change affects usage, update the README / API docs / module
   header accordingly.
5. **Report.** Note what you documented and anything still unclear that needs an owner.

## Notes

- Keep comment density consistent with the surrounding file.
- User-facing docs follow the repo's language rule; internal comments follow the file.
