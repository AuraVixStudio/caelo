# My Visual Novel — Ren'Py starter

Created from the Caelo **Ren'Py — Visual Novel Starter** template.

## Layout

```
game/
  script.rpy     # the story: characters, scenes, a branching menu
  options.rpy    # project name, version, sound channels, transitions
images/          # put bg <name>.png and <char> <pose>.png assets here
audio/           # music / sfx / voice
```

## Run it

1. Install the [Ren'Py SDK](https://www.renpy.org/) (8.x).
2. Open this folder in the Ren'Py launcher (or `renpy.sh <this-folder>`).
3. Press **Launch Project**.

## Next steps

- Replace the placeholder `scene bg room` / `show eileen happy` with real art
  under `images/`.
- Add new `label`s and `menu:` blocks in `script.rpy` to expand the story.
- The bundled **Ren'Py — New Scene** skill can scaffold additional scenes for you.
