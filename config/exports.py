"""The four ways to take something out of the product.

One catalogue, because the list is read for two different jobs and they were
drifting.  ``core.views.exports`` reads it to decide whether a posted ``kind``
is real; ``core.insights`` reads it to name the rows of the export table.  A
fifth export added to only one of those is either silently refused or silently
missing from the report, and neither failure says which list was not updated.

Data only, and Django-free, like the rest of ``config``.  The order is
cheapest-first, which is also the order the exports were argued for in
``tasks/b-provision-exports.md``.
"""

#: ``(kind, label, description)``.  ``kind`` is the value stored in
#: ``EngagementEvent.context["kind"]``, so it is a record and does not change.
EXPORT_KINDS: tuple[tuple[str, str, str], ...] = (
    ("citation", "Citation", "A string copied into somebody else's document."),
    ("provision_pdf", "Provision", "One provision at one date, laid out to print."),
    ("results_csv", "Results CSV", "A result set for auditing a building against a date."),
    ("comparison_pdf", "Comparison", "Two versions and the pairing, laid out to print."),
)

#: The kinds alone, for the "is this a real export?" test.  Derived rather
#: than written out again — that second copy is what this module exists to
#: remove.
EXPORT_KIND_NAMES: frozenset[str] = frozenset(kind for kind, _, _ in EXPORT_KINDS)
