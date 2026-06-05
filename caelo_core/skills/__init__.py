"""Skille (lokalne pakiety) — M14-B6.

Skill = folder z `SKILL.md` (instrukcje + frontmatter) + opcjonalne skrypty/zasoby.
Odkrywane z dwóch źródeł: **wbudowane** (`caelo_core/skills/builtin/`, pakowane,
read-only — Ren'Py/DAZ jako pierwsze) oraz **użytkownika** (`config.SKILLS_DIR`).
Włączone skille są wstrzykiwane do system promptu agenta (jak CAELO.md). Most do
dorobku Ren'Py/DAZ i rozbieg pod marketplace (M16).
"""

from caelo_core.skills.manager import SkillManager

__all__ = ["SkillManager"]
