"""The one tag-span pattern this product splits provision HTML on.

Two callers need it and must agree, because they compose: ``core.cross_refs``
locates a citation's character offsets in the *text* of a version's html, and
``api.formatters`` wraps those same texts in ``<mark>`` and in diff spans.  A
second copy of the pattern is how one of them starts treating a byte as markup
that the other treats as text, and the offsets stop lining up.

The capture group is load-bearing for ``re.split``: it keeps each tag in the
returned list, so a splitter can pass tags through untouched.  ``finditer``
and ``fullmatch`` read the whole match and are unaffected by it.
"""

import re

#: Matches one tag span, capturing it.
HTML_TAG_RE = re.compile(r"(<[^>]+>)")
