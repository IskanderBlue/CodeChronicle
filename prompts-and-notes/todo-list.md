# TODO list

## General
- `scripts/extract_keywords.py` only iterates `sections` — also include `tables` keywords when rebuilding the keyword list.
- Add a "Parsed via OCR; may contain errors." note to PDF-derived table markdown displayed in search results. e-Laws tables (OBC) have exact text and don't need this disclaimer.

## eventually
- settings: should have a clicker ui to select the folder in addition to the text input.
  - Troublesome; 
    - codex says no way to do this without triggering user-unfriendly warning; won't work for Firefox anyway.
    - Could do single-file drag-and-drop, but this doesn't store the full path; would have to store file in local IndexedDB, copyright issues.
    - Could use IndexedDB to store the full path, but this would require a custom implementation.

## Maybe
- top bar: no longer fits at md even; must swap out at lg? Marginal.

### complete
- ~~we want more detail returned from search_results; maybe title too.~~ 
	- done: added page_end, code_display_name via verbose=True
- ~~need loading indicator when search is running.~~ 
	- done: inject spinner into results area on submit
- ~~"Full text not available for this code in the Free tier" displays if no pdf available even for pro.~~ 
	- done: changed to "Full text not available for this code edition."
- ~~periodically check for style violations.~~ 
	- done: ran ruff check
- ~~implement/test pdf display.~~ 
	- ~~test with NBC 2025.~~
	- done: PDF.js inline rendering with expand/collapse, user-specific PDF directory in settings, serve_pdf view
- ~~search history: shows "{{ result.title }}" rather than the actual title.~~
	- done: changed to display actual title
- ~~search history: should click through to the results.~~
	- done: added click-through to results
- ~~update file references eg. NBC_2025.pdf to whatever the map says the default d/l name is.~~
	- done: updated file references
- ~~general: light mode is too bright; bg-neutral-50 should probably be closer to bg-neutral-200 for large fields.~~
	- done: changed bg-neutral-50 to bg-neutral-200 for large fields
- ~~update `STYLE_GUIDE.md`: add the `coloured-logger` package to imports and try `from coloured_logger import Logger`; `logger = Logger(__name__)`; `logger.<appropriate level>(<message>)` rather than `print(<message>)`; reserve print for debugging purposes only.~~
	- done
- ~~top bar: move password, logout into Settings; may want to add tabs to settings page or otherwise make all setting changes clearly accessible; move settings to right of top bar~~
	- done
- ~~now that we have pdfs for major provinces, unlock non-ON; default to None for Province.~~
  - done
- ~~Use `html` (`notes_html` too for table) if no pdf is available (eg. Ontario before current handbook)~~
	- done
- ~~If no page is available (eg. Ontario before current handbook), link to the regulation,~~
  - done 
  - ideally to the specific section or subsection.
    - Not feasible
- ~~settings: should include links to all of the pdfs we can source.~~
	- done: added links from Canada_building_code_mcp/docs/PDF_DOWNLOAD_LINKS.md
- ~~include sections explicitly~~
  - Numeric sections 2-5 1-2 digit sections separated by periods with optional table- or <single-letter>- checked.
- ~~implement stripe subscriptions.~~
  - presumably done; test when stripe gets verified bank account
- ~~put link to pdf in upload ui~~
	- done
- ~~notify users if they get rate-limited~~
  - done: rate-limit banner with signup/login (anon) or upgrade (authenticated) CTAs; free users no longer rate-limited
- ~~show notes_html when relevant~~
	- done: pass notes_html through formatter, display below content with "Notes" separator
- ~~refactor for clarity~~
	- done: implemented refactor.md — service layer (services/search_service.py), split api/search.py into api/search/ package (engine.py + orchestration.py), split core/views.py into core/views/ package (search.py, history.py, billing.py, pages.py), added CI lint/test workflow (.github/workflows/ci.yml)
- ~~Use support@, billing@, privacy@, legal@, admin@, rob@ (codechronicle.ca) wherever appropriate.~~
  - done
- ~~UI overrides date/province; API doesn’t~~
  - ~~api should too~~
  - done
