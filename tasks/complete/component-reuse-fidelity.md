# Component reuse: one search form, one column grid

Status: **done**. Shipped in commit `d75c5fa`, with the landing page. The suite
is green (625 tests at the time of the move); `ruff check .` is clean.

The landing page mounts the product's own partials as worked examples
(`tasks/complete/landing-page.md`). Two of those mounts copied the product instead of
using it, and a third surface — the verification-rail guide — showed a component
in a colour no reader ever meets. All three are fixed.

## The rule

A copy of a component is a claim about the product that nothing keeps true. A
number copied out of a component's layout is the same defect: it rots the moment
that layout changes, and nothing fails when it does.

Both copies here were already wrong before anybody noticed. The search bars had
lost the Jurisdiction cell. The transcribed width was 964px against a real
933px, because the subtraction spans four files and one padding rule was missed.

## 1 — One search form

`templates/partials/_search_form.html` is now the only search bar. Three call
sites render it:

| Call site | Mode |
|---|---|
| `templates/search.html` | `live` |
| `templates/landing.html`, the hero | `handoff` |
| `templates/landing.html`, section III row 01 | `handoff` |

`mode` forks behaviour, not markup:

- `live` — htmx `hx-post` to `core:search_results`. Keeps `id="search-form"`
  (the relevance-floor control re-runs the query with `hx-include`) and the bare
  `id="query"` (the search page's script focuses it). Posts `query`, `date`,
  `province`.
- `handoff` — a plain GET to `core:search`, which reads `?q=` and `?d=`. That
  pair is the public link contract the "try this" links share.

`id_prefix` namespaces the ids, because two of these forms appear on one page.
The AS-OF input needs no id: its label wraps it.

The landing view supplies row 01's prefill (`SPECIMEN_QUERY`,
`SPECIMEN_QUERY_DATE`) because the AS-OF cell formats a `date`, and a template
literal can only be a string.

Removed: `.lp-field .cell*` / `.lp-field label` / `.lp-field input*` and the
whole `.lp-spec .qbar` block. `.lp-field` now sets margin only.

## 2 — One column grid

`base.html` declares the working measure once, as tokens:

    --ws-max: 1700px;   --ws-pad: 8rem;   --ws-gap: 1.5rem;
    --ws-nav: 20rem;    --ws-rail: 19rem;
    --ws-centre: calc(min(100vw, var(--ws-max)) - var(--ws-pad)
                      - var(--ws-nav) - var(--ws-rail) - 2 * var(--ws-gap));

`--ws-pad` is the page shell's `lg:px-8` plus each working page's own `sm:px-8`.
`--ws-nav` defaults to the wider of the two navigation tracks, so `--ws-centre`
is the narrower of the two centre columns and a specimen is never wider than a
real result.

`.ws-cols` builds the grid from those tokens. It sets **only** the grid
properties: `display` stays with each call site's utility, because base.html's
inline style block loads *before* `tailwind.css` and so loses every specificity
tie to a utility class.

- `templates/regulation/provision_permalink.html` — `ws-cols lg:grid`, plus
  `[--ws-nav:18rem]` for its narrower first track.
- `templates/partials/search_results_partial.html` — `hidden ws-cols lg:grid`.
- `templates/landing.html` — `.lp-mount-centre` reads `var(--ws-centre)`,
  `.lp-mount-rail` reads `var(--ws-rail)`.

Verified at a 1440px viewport: the landing's row 03 band comes out 640px, the
same figure the search grid gives, and the rail shows the staggered two-row
labels with the badge above the sentence — as the permalink page does.

## 3 — The verification-rail guide

The guide rendered `_attestation_rail.html` on the page background. In the
product the rail is never seen alone: it is the body of the IN FORCE band, which
paints `bg-secondary-soft`. The guide taught the object in a colour the reader
will never meet, and its ring knockouts filled against the wrong backdrop.

The handoff note said `_provenance_band.html` could not render from
`core/rail_examples.py`, which supplies rail geometry only. That was too
pessimistic: everything the band needs beyond `result.rail` is optional, so it
renders unchanged. Only the copy button had to go, because an illustrative date
has no reference to copy — it takes the `in_legend` guard the rail already uses.
`rail_examples.py` needed no change.

The guide's panel also paints `--surface-2` and holds the symbol key's ring
knockout, so it now declares `[--backdrop:var(--surface-2)]` — the same contract
`_provenance_band.html` follows.

The examples container scrolls (`.rail-legend .legend-rail { overflow-x: auto }`)
so an off-line consolidation caption that runs past the band's edge stays
reachable. That is unchanged behaviour.

## Guards

`core/tests/test_templates.py::TestOneOfEachComponent` (11 tests) reads the
template sources, because a copy renders perfectly well on its own:

- the search page renders the shared form; the landing page renders it twice;
- the partial keeps `id="search-form"` and prefixes `id="…query"`;
- the Jurisdiction cell does not sit behind the mode flag;
- neither working surface declares its own `grid-cols-[…]`;
- the tracks and `--ws-centre` are declared once in `base.html`;
- `.lp-mount-centre` and `.lp-mount-rail` read a `--ws-*` token;
- the guide renders the band and not the bare rail, and declares its backdrop.

`core/tests/test_landing.py::TestSectionThreeSpecimens` gained
`test_the_query_specimen_is_the_shipping_search_form`.
`TestBackdropKnockouts` in `test_templates.py` is unchanged and still passes.

## Verifying by screenshot

Headless Chrome reports `prefers-color-scheme: dark`, and these faults hide in
dark mode because most tokens are near-black. Force light:

    chrome --headless --disable-gpu --no-sandbox --hide-scrollbars \
      --window-size=1440,7800 --virtual-time-budget=7000 \
      --blink-settings=preferredColorScheme=1 \
      --screenshot=C:\abs\path\out.png http://127.0.0.1:8009/about/

`--screenshot` needs an absolute Windows path. Windows filenames are
case-insensitive: do not write a crop to `PW2400.png` beside a screenshot named
`pw2400.png` — the second write silently destroys the first. Drop
`--hide-scrollbars` when you need to know whether a container scrolls.

The guide is at `/verification-rail/`, not `/verification-guide/`.

Templates do not hot-reload; restart `runserver` after a template edit. New
Tailwind utility classes do not exist until the CSS is rebuilt:

    .\tailwindcss.exe -i static/css/input.css -o static/css/tailwind.css --minify

## What shipped

All of the following went in with the landing page, in commit `d75c5fa`:

- `templates/landing.html` (new), `core/views/landing.py` (new),
  `core/tests/test_landing.py` (new), `tasks/landing-page.md` (new)
- `templates/partials/_search_form.html` (new)
- `templates/base.html` — the `--backdrop` token, the two knockout rules, the
  `--ws-*` tokens and `.ws-cols`
- `templates/search.html`, `templates/partials/search_results_partial.html`,
  `templates/regulation/provision_permalink.html`,
  `templates/partials/_provenance_band.html`,
  `templates/verification_guide.html`
- `core/urls.py`, `core/views/search.py`, `core/views/__init__.py`,
  `code_chronicle/settings/base.py` — the routing split and `?d=`
- `core/tests/test_templates.py`, `core/tests/test_engagement.py`

`conversation-notes.txt` and `tasks/error-bounty.md` are still untracked. They
belong to someone else — leave them alone.
