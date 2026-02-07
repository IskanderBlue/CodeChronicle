# TODO list

- ~~we want more detail returned from search_results; maybe title too.~~ done: added page_end, code_display_name via verbose=True
- ~~need loading indicator when search is running.~~ done: inject spinner into results area on submit
- ~~"Full text not available for this code in the Free tier" displays if no pdf available even for pro.~~ done: changed to "Full text not available for this code edition."
- ~~periodically check for style violations.~~ done: ran ruff check
- ~~implment/test pdf display.~~ done: PDF.js inline rendering with expand/collapse, user-specific PDF directory in settings, serve_pdf view
    - test with NBC 2025.
    - what does mcp return for ontario/html codes?
- handle display when sections and subsections are both returned (e.g. B-3.2.9 & B-3.2.9.1).

## Eventually:
- separate repo for terraform infrastructure.
- separate repo for populating historical code maps.
- implement stripe subscriptions.
