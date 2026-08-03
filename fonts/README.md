# Vendored faces for the social card

These files are **build inputs**, not static assets. `manage.py
make_social_card` reads them to draw `static/images/social-card.png`. The
server never opens them, and `collectstatic` never collects them — the site
loads the same families from Google Fonts at request time.

They are here because the card must carry the same wordmark as the app bar.
A drawing program cannot use a CDN font, and the machine that draws the card
has no Source Serif 4 installed, so the card fell back to Georgia and the
wordmark on a forwarded link was not the wordmark on the site.

## What each file is

| File | Role on the card |
|---|---|
| `SourceSerif4-Bold.ttf` | "Code", and the subtitle |
| `SourceSerif4-MediumItalic.ttf` | "Chronicle" — the app bar sets the second half in italic |
| `SourceSerif4-SemiBold.ttf` | spare weight for smaller serif text |
| `JetBrainsMono-Regular.ttf` | dates and the domain |
| `JetBrainsMono-SemiBold.ttf` | column headings |

## Provenance

Both families come from the Google Fonts repository, under the SIL Open Font
License 1.1. The licence for each family is beside the files
(`OFL-SourceSerif4.txt`, `OFL-JetBrainsMono.txt`).

- `ofl/sourceserif4/SourceSerif4[opsz,wght].ttf`
- `ofl/sourceserif4/SourceSerif4-Italic[opsz,wght].ttf`
- `ofl/jetbrainsmono/JetBrainsMono[wght].ttf`

## How they were made

The upstream files are variable fonts with every weight and a full character
set; `SourceSerif4` alone is 1.2 MB, over this repository's large-file gate.
Each face here is pinned to one weight and subset to the characters the card
can print (ASCII, the en dash, the bullet), which brings the set to about
165 KB.

`fonttools` did the work and is **not** a project dependency. To remake them,
install it into a scratch directory and pin each face:

```python
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
from fontTools import subset

font = instancer.instantiateVariableFont(
    TTFont("SourceSerif4.ttf"), {"wght": 700, "opsz": 60}, inplace=True
)
options = subset.Options()
options.layout_features = ["kern", "liga", "calt"]
options.name_IDs = ["*"]
subsetter = subset.Subsetter(options=options)
subsetter.populate(text="".join(chr(c) for c in range(0x20, 0x7F)) + "–—• ")
subsetter.subset(font)
font.save("SourceSerif4-Bold.ttf")
```

The weights match the app bar: `templates/base.html` sets the wordmark in
`font-serif font-bold` with the second half `italic font-medium`.
