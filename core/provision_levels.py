"""Which provision levels are headings rather than text.

Every level here carries an empty body on purpose — a division, a part, a
section and a subsection are containers, and their substantive text lives in
the articles below them.  So an empty ``html`` at one of these levels is not
missing data, and no surface may report it as a gap.

One home because three surfaces answer the same question and must answer it
the same way: the result card's ``is_structural``, the API's ``is_container``,
and the permalink page's contents view.  Two of them held their own copy of
this set before, one public and one private, with a comment in each saying it
had to match the other.
"""

from core.models import CodeEditionProvision

CONTAINER_LEVELS = frozenset(
    {
        CodeEditionProvision.Level.DIVISION,
        CodeEditionProvision.Level.PART,
        CodeEditionProvision.Level.SECTION,
        CodeEditionProvision.Level.SUBSECTION,
    }
)
