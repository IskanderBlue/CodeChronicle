# TODO list

## API
- UI overrides date/province; API doesn’t
  - api should too

## General
- Implement: https://x.com/ryancarson/status/2016520542723924279
- Harden static asset versioning/caching: use Django hashed static filenames (Manifest storage), ensure deploy-time `collectstatic`, and keep Cloudflare caching safe for `/static/*`.
- NBC first.
- show date-based changes
  - transition periods

## Ponder
- Think through how to handle what search UI displays when sections and subsections are both returned (e.g. B-3.2.9 & B-3.2.9.1).
  - check whether all subsections are returned; if so, display their parent; otherwise, display specific subsections? Can discuss.


## code dating — transition provisions to handle
Several codes have conditional effective dates with grace periods for in-stream projects.
The `get_applicable_codes()` logic currently treats dates as hard cutoffs; these need nuance.

- **BCBC 2024** (effective 2024-03-08): The 2018 BC Building Code's requirements for earthquake design and adaptable dwelling units continued to be in effect for permits applied for until March 9, 2025. In-stream projects, where certain criteria are met, are exempt from the 2024 BC Building Code's adaptable dwelling unit and earthquake requirements.
- **QCC Building 2020** (effective 2025-04-17): The amendments to Chapter I, Building, of the Construction Code came into force on 17 April 2025 (Order in Council 437-2025, 2025 G.O. 2, 994). Nevertheless, Chapter I of the Construction Code as it read on 16 April 2025 may apply to the construction or transformation of a building, as defined in that Chapter, provided that the work begins before 17 October 2026.
- **QECB 2020** (effective 2024-07-13): The amendments to Chapter I.1, Energy Efficiency of Buildings, of the Construction Code came into force on 13 July 2024 (Order in Council 850-2024, 2024 G.O. 2, 1868). Nevertheless, Chapter I.1 of the Construction Code as it read on 12 July 2024 may apply to construction work referred to in sections 1.1.2 and 1.1.3, provided that the work begins before 13 January 2025.
- **QPC 2020** (effective 2024-07-11): The amendments to Chapter III, Plumbing, of the Construction Code came into force on 11 July 2024 (Order in Council 983-2024, 2024 G.O. 2, 2635, amended by Order in Council 1071-2024, 2024 G.O. 2, 3129). Nevertheless, Chapter III of the Construction Code as it read on 10 July 2024 may apply to construction work on a plumbing system, provided that the work begins before 11 January 2025.
- **QSC 2020** (effective 2025-04-17): The amendments to Chapter VIII, Buildings, of the Safety Code came into force on 17 April 2025 (Order in Council 438-2025, 2025 G.O. 2, 1175), except that sub-subsection VIII of subdivision 1 of Division IV will come into force on 2 December 2027 (Order in Council 1035-2015, 2015 G.O. 2, 3189, and am.); Article 2.1.3.7. of Division B of the NFC will come into force on 17 April 2028. Nevertheless, Chapter VIII of the Safety Code as it read on 16 April 2025 may apply the day before 17 October 2026.

## eventually
- add optional `transition_end` field to `CodeEdition`; when set, `get_applicable_codes()` returns both old and new editions during the overlap window.
- settings: should have a clicker ui to select the folder in addition to the text input.
  - Troublesome; 
    - codex says no way to do this without triggering user-unfriendly warning; won't work for Firefox anyway.
    - Could do single-file drag-and-drop, but this doesn't store the full path; would have to store file in local IndexedDB, copyright issues.
    - Could use IndexedDB to store the full path, but this would require a custom implementation.

## Maybe
- top bar: no longer fits at md even; must swap out at lg? Marginal.
- search: don't double up if id and title are identical
  - Leave this be; fix via better data.

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
