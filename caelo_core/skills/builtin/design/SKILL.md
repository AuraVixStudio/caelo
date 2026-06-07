---
name: Design doc (write -> review loop)
description: Draft a design document and iterate writer/reviewer subagents until consensus.
triggers: [design, design doc, rfc, proposal, architecture, design loop]
---

# Design doc (write -> review loop)

Use this to produce a vetted design document for a non-trivial task before implementing.
You iterate a `design-doc-writer` (writes in an isolated copy) against a
`design-doc-reviewer` (read-only critique) until the reviewer approves.

## Loop

1. **Draft.** `delegate` a `design-doc-writer` with the problem, constraints and any
   relevant code paths. It writes a Markdown design doc in its isolated copy.
2. **Review.** `delegate` a `design-doc-reviewer` to critique that document. The reviewer
   ends with `VERDICT: APPROVE` or `VERDICT: REVISE`.
3. **Revise.** If the verdict is REVISE, `delegate` a `design-doc-writer` again with the
   reviewer's concerns and instruct it to address every point.
4. **Repeat** steps 2–3 until the verdict is APPROVE, or you reach the round limit
   (default **3**; honor an "effort N" of 1–5 as N rounds).
5. **Summarize.** Report the agreed design (path + key decisions) and the final verdict;
   the document awaits the user's merge review.

## Notes

- The writer works in an isolated worktree — the document is only applied after the user
  reviews and merges it.
- Pass the document path/content forward between rounds so each subagent has the context
  it needs (summaries, not transcripts).
