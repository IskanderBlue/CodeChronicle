"""
The reader-facing name of each code system.

Data only, and Django-free, like the rest of ``config``.  The lookups that
prefer the ``Code`` row live in :mod:`core.code_names`.
"""

#: The name a reader would use for each code system.
#:
#: This lives here rather than in the CCM payload because it is a presentation
#: choice and not a mapping result: CCM writes one file per edition, so a
#: code-system fact would repeat in every one of them and a wording change
#: would need a mapping run.  ``load_edition`` applies this map to the ``Code``
#: row, which keeps the value in version control instead of in whatever seeded
#: the row last — the state that left ``OBC`` unnamed while every code the
#: product does not serve kept its own name.
#:
#: Add a code here when its first edition loads.  A code that is absent falls
#: back to its own short form, which reads as trade shorthand but is never
#: wrong.
DISPLAY_NAMES = {
    "OBC": "Ontario Building Code",
    "NBC": "National Building Code",
    "NFC": "National Fire Code",
    "NPC": "National Plumbing Code",
    "ABC": "Alberta Building Code",
}
