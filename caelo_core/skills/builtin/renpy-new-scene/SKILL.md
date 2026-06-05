---
name: Ren'Py — New Scene
description: Scaffold a new Ren'Py visual-novel scene (label, dialogue, choices, transitions).
triggers: [renpy, visual novel, vn scene, .rpy]
---

# Ren'Py — New Scene

Use this when the user wants to add a new scene to a Ren'Py project.

## Steps

1. Locate the `game/` directory and the script files (`*.rpy`). Read `script.rpy`
   and any existing `scenes/` files to match the project's conventions (character
   `define`s, image names, naming of labels).
2. Create a new label `label <scene_name>:` in a dedicated `game/scenes/<scene_name>.rpy`
   file (or append to the relevant script), wired from the calling label with `call`/`jump`.
3. Within the scene use the project's existing primitives:
   - `scene bg <name>` for backgrounds, `show <char> <pose>` for sprites,
   - `with dissolve` / `with fade` for transitions already defined in the project,
   - character-prefixed dialogue lines (`e "..."`) using existing `Character` defines.
4. For branching, use a `menu:` block with 2–4 choices, each `jump`ing to a labelled
   continuation; keep variables in `default` at the top of the file.
5. Do not invent asset filenames — only reference images/audio that already exist, or
   clearly flag any new asset the user must add.

## Checklist

- New label is reachable from the existing flow.
- Every `show`/`scene`/`play` references an existing asset or is flagged as TODO.
- The file passes `renpy.sh <project> lint` if the Ren'Py SDK is available
  (run via the agent's gated `run_command`).
