"""Display preferences: coercion, storage, and the search-view plumbing."""

import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory
from django.urls import reverse

from config.search_limits import (
    CLOSE_MATCH_THRESHOLD,
    MAX_MATCH_THRESHOLD,
    coerce_match_threshold,
    score_buckets,
)
from core.models import User
from core.search_prefs import resolve_match_threshold


class TestMatchThresholdCoercion:
    @pytest.mark.parametrize("value", [0.0, 0.37, 0.8, 1.24, 2.5, 5.0])
    def test_any_value_in_range_is_kept(self, value):
        # Continuous, not a set of tiers: the reader puts the line where the
        # distribution says the tail starts, which is a different number on
        # every query.
        assert coerce_match_threshold(value) == value
        assert coerce_match_threshold(str(value)) == value

    def test_rounded_to_the_control_step(self):
        assert coerce_match_threshold(0.8149) == 0.81

    @pytest.mark.parametrize("value,expected", [(-1, 0.0), (99, MAX_MATCH_THRESHOLD)])
    def test_out_of_range_clamps_rather_than_resets(self, value, expected):
        # Clamping keeps the reader's intent (as low/high as possible); a reset
        # to the default would silently contradict where they left the line.
        assert coerce_match_threshold(value) == expected

    @pytest.mark.parametrize("value", ["abc", None, "", True, float("nan")])
    def test_unusable_input_falls_back_to_the_default(self, value):
        assert coerce_match_threshold(value) == CLOSE_MATCH_THRESHOLD

    def test_zero_is_a_real_value_not_a_falsy_reject(self):
        # 0.0 means "count everything"; a truthiness check would bounce it back
        # to the default and the control would look broken while appearing
        # to work.
        assert coerce_match_threshold(0.0) == 0.0
        assert coerce_match_threshold("0.0") == 0.0


class TestScoreBuckets:
    def test_counts_land_in_width_sized_bands(self):
        # 0.05 bands: 0.0 -> index 0, 0.06 -> index 1, 0.83 -> index 16.
        assert score_buckets([0.0, 0.06, 0.07, 0.83]) == (
            [1, 2] + [0] * 14 + [1]
        )

    def test_buckets_partition_the_scores(self):
        scores = [0.03, 0.41, 0.42, 1.19, 2.2]
        assert sum(score_buckets(scores)) == len(scores)

    def test_empty_in_empty_out(self):
        assert score_buckets([]) == []


def _request(user, data=None):
    """A request carrying ``data`` as POST, or a GET when data is None."""
    factory = RequestFactory()
    request = factory.post("/search/", data) if data is not None else factory.get("/search/")
    request.user = user
    # A real SessionStore, not a dict: the helpers write through the session
    # API, and a dict would pass here while failing in the view.
    request.session = SessionStore()
    return request


@pytest.mark.django_db
class TestStorage:
    """One preference, two stores: a User field or the session."""

    def test_default_without_a_stored_floor(self):
        assert resolve_match_threshold(_request(AnonymousUser())) == CLOSE_MATCH_THRESHOLD

    def test_anonymous_floor_lives_in_the_session(self):
        request = _request(AnonymousUser(), {"match_threshold": "1.17"})

        assert resolve_match_threshold(request) == 1.17
        assert request.session["match_threshold"] == 1.17

    def test_signed_in_floor_lives_on_the_user(self):
        user = User.objects.create_user(email="pref@example.com", password="x")

        assert resolve_match_threshold(_request(user, {"match_threshold": "0.43"})) == 0.43

        user.refresh_from_db()
        assert user.match_threshold == 0.43

    def test_signed_in_floor_survives_a_new_session(self):
        # The point of storing it on the account rather than the session: the
        # line stays where they left it on the next visit, next device.
        user = User.objects.create_user(email="stays@example.com", password="x")
        resolve_match_threshold(_request(user, {"match_threshold": "1.36"}))

        fresh = _request(User.objects.get(pk=user.pk))
        assert resolve_match_threshold(fresh) == 1.36

    def test_a_search_without_the_field_reads_it_back(self):
        # Only the control posts a threshold; an ordinary search must not
        # silently reset the line to the default.
        first = _request(AnonymousUser(), {"match_threshold": "0.41"})
        resolve_match_threshold(first)

        plain = _request(AnonymousUser(), {"query": "fire"})
        plain.session = first.session
        assert resolve_match_threshold(plain) == 0.41

    def test_stored_value_is_the_coerced_one(self):
        # Storing the coercion but rendering the raw request is how a control
        # ends up disagreeing with the list beneath it.
        request = _request(AnonymousUser(), {"match_threshold": "-3"})

        assert resolve_match_threshold(request) == 0.0
        assert request.session["match_threshold"] == 0.0


def _stub_search(seen):
    def _run(query, **kwargs):
        seen.update(kwargs)
        return {
            "success": True, "results": [], "applicable_codes": [],
            "parsed_params": {}, "locked_editions": {},
            "match_threshold": kwargs.get("match_threshold"),
        }
    return _run


@pytest.mark.django_db
class TestSearchViewPlumbing:
    """The control posts back through the search view itself."""

    def test_posted_floor_is_persisted_and_passed_down(self, client, monkeypatch):
        seen: dict = {}
        monkeypatch.setattr("core.views.search.run_search", _stub_search(seen))

        response = client.post(
            reverse("core:search_results"),
            {"query": "fire", "match_threshold": "1.23"},
        )

        assert response.status_code == 200
        assert seen["match_threshold"] == 1.23
        assert client.session["match_threshold"] == 1.23

    def test_signed_in_floor_round_trips_through_the_view(self, client, monkeypatch):
        seen: dict = {}
        monkeypatch.setattr("core.views.search.run_search", _stub_search(seen))
        user = User.objects.create_user(email="viewpref@example.com", password="pw")
        client.force_login(user)

        client.post(
            reverse("core:search_results"), {"query": "fire", "match_threshold": "1.42"}
        )
        user.refresh_from_db()
        assert user.match_threshold == 1.42

        # A later search with no threshold in the post reads it back off the
        # account, not the session and not the default.
        seen.clear()
        client.post(reverse("core:search_results"), {"query": "guards"})
        assert seen["match_threshold"] == 1.42
