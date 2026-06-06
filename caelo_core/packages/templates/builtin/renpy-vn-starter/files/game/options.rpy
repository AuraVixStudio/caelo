# Ren'Py configuration / options for the project.
# Trimmed from the Ren'Py default to the essentials a starter needs.

define config.name = _("My Visual Novel")
define config.version = "0.1"

define gui.show_name = True

define build.name = "MyVisualNovel"

## Sound channels --------------------------------------------------------------
define config.has_sound = True
define config.has_music = True
define config.has_voice = True

## The transition used when entering/leaving the game menu.
define config.enter_transition = Dissolve(.2)
define config.exit_transition = Dissolve(.2)

## Save directory (defaults are usually fine; set per-project to avoid clashes).
define config.save_directory = "MyVisualNovel-1700000000"
