"""The list-insertion punctuation guide (``web:list_punctuation``).

Static copy page, so the tests are deliberately about the two things that can
actually break it: template rendering (Django tokenises tags everywhere, and a
leaked tag would ship as literal text) and the framing the page exists to get
right — a supplied mark and an enacted mark shown as distinguishable, and no
e-Laws divergence asserted without its citation.  See
``tasks/complete/list-insertion-punctuation.md``.
"""

import pytest
from django.urls import reverse


@pytest.mark.django_db
class TestListPunctuationPage:
    def test_renders_ungated_for_anonymous(self, client) -> None:
        response = client.get(reverse("web:list_punctuation"))
        assert response.status_code == 200
        assert "list_punctuation.html" in [t.name for t in response.templates]

    def test_no_template_syntax_leaks_into_the_page(self, client) -> None:
        body = client.get(reverse("web:list_punctuation")).content.decode()
        for leak in ("{%", "{{", "{#"):
            assert leak not in body, f"unrendered template syntax {leak!r} in page body"

    def test_marks_the_supplied_separator_apart_from_the_enacted_one(self, client) -> None:
        """The whole point of the page: the join comma is ours, the serial comma
        before *or* is the regulation's.  If the worked example stops rendering
        both roles, the page has lost its argument."""
        body = client.get(reverse("web:list_punctuation")).content.decode()
        assert 'class="supplied"' in body
        assert 'class="enacted"' in body

    def test_every_elaws_divergence_claim_carries_a_citation(self, client) -> None:
        """An uncited swipe at the official source is worse than no sentence at
        all — each divergence bullet names the provision and the filing."""
        body = client.get(reverse("web:list_punctuation")).content.decode()
        for citation in ("8.2.1.5.", "350/06", "2.7.2.1.", "1.1.3.2.", "22/98"):
            assert citation in body, f"missing citation {citation!r}"

    def test_reachable_from_data_sources(self, client) -> None:
        body = client.get(reverse("web:data_sources")).content.decode()
        assert reverse("web:list_punctuation") in body
