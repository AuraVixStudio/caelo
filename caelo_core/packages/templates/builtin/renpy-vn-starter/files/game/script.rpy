# The script of the game goes in this file.
#
# Generated from the Caelo "Ren'Py — Visual Novel Starter" template.
# Replace placeholder assets in game/images/ and game/audio/ with your own.

# Declare characters used by this game. The color argument colorizes the
# name of the character for dialogue.
define e = Character("Eileen", color="#c8ffc8")


# The game starts here.
label start:

    # Show a background. This uses a placeholder; drop a real image at
    # game/images/bg room.png (or .jpg) to replace it.
    scene bg room

    # Show a character sprite. A placeholder is used here.
    show eileen happy

    # These display lines of dialogue.
    e "You've created a new Ren'Py game from the Caelo starter template."

    e "Want to see how a branching choice works?"

    menu:
        "Yes, show me a branch.":
            jump branch_demo

        "No, just continue.":
            jump ending

label branch_demo:
    e "Menus let the player steer the story. Each choice can [[jump]] to a label."
    e "Add more labels, scenes and choices to grow your visual novel."
    jump ending

label ending:
    e "Once you add your own art and writing, this is a real Ren'Py game."

    # This ends the game.
    return
