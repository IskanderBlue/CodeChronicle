# Viewer edition-nav via ProvisionMapping — SUPERSEDED

**Status: SUPERSEDED 2026-06-10 by `tasks/provision-lineage.md`. Do not
implement this plan.**

This task planned to *fix* the viewer's prev/next-edition buttons by
resolving through `ProvisionMapping` (mapping-first, same-id fallback, with
split/merge policy and chain-walking). The plan is obsolete because:

1. The single-button UI is being **replaced** by lineage rows (a list of
   predecessor/successor links, labelled by edition), which dissolves the
   split/merge single-endpoint policy problem.
2. Mappings are confirmed to be emitted only between **adjacent** editions,
   so the chain-walking concern never arises.
3. The same-id heuristic this task wanted to demote to a fallback survives
   only *inside* the new lineage resolver (`core/provision_lineage.py`,
   planned) as the same-id-on-covered-transition lookup — including the
   division-preference tiebreak.

The original problem statement (the `(edition, provision_id)` + division
preference heuristic in `core/views/search.py` silently picks the wrong
provision on renumber/split/merge) remains true and is fixed by the
superseding task, which deletes `_build_viewer_navigation` /
`_build_viewer_url_params` outright.
