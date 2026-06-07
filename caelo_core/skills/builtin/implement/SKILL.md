---
name: Implement (multi-agent loop)
description: Orchestrate an implement -> review -> fix loop with subagents until reviewers sign off.
triggers: [implement, build feature, multi-agent, delegate, implement loop]
---

# Implement (multi-agent loop)

Use this when you (the orchestrator) should implement a non-trivial change by fanning
work out to subagents and iterating until the change is clean. You drive the loop with
the `delegate` tool; subagents work in isolated copies and their changes await the
user's merge review.

## Loop

1. **Plan & split.** Break the task into independent, self-contained chunks. Note the
   acceptance criteria you will check against.
2. **Implement.** `delegate` one `implementer` per chunk (parallel — pass them in a
   single `delegate` call). Give each a precise, standalone instruction.
3. **Review.** When the implementer summaries return, `delegate` a `reviewer` (one, or
   one per area) to review the changes for correctness, security and quality. Tell the
   reviewer exactly which files/areas to look at.
4. **Fix.** Collect the reviewer findings. If there are any blocking findings,
   `delegate` an `implementer` to fix them (reference the specific findings).
5. **Repeat** steps 3–4 until reviewers report no blocking findings, or you reach the
   round limit. Default to **3 rounds**; if the user asked for an "effort N" (1–5),
   use N rounds.
6. **Summarize.** Report what changed, the final review verdict, and that the changes
   are staged for the user's merge review.

## Notes

- Keep your own context clean: integrate the returned **summaries**, not transcripts.
- Do not exceed the team limits (parallelism / subagent count / turn budget) — they are
  enforced; design your fan-out to fit.
- If a chunk turns out to depend on another, sequence those `delegate` calls instead of
  running them in parallel.
