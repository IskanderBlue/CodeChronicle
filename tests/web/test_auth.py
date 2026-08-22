"""The credential itself: what a key is, and what the API accepts."""

import json
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from core.models import ApiKey, EngagementEvent, SearchHistory, User
from telemetry.throttle_notice import notify_api_throttle
from web.api.auth import (
    API_SEARCHES_BEFORE_THROTTLE,
    API_THROTTLE_MAX_SECONDS,
    API_THROTTLE_STEP_SECONDS,
    bearer_token,
    resolve_key,
    searches_today,
    throttle_delay,
)


@pytest.mark.django_db
class TestApiKeyModel:
    def setup_method(self):
        self.user = User.objects.create_user(email="pro@example.com", pro_courtesy=True)

    def test_the_token_is_not_stored(self):
        """Only the hash reaches the database."""
        key, token = ApiKey.generate(self.user, "takeoff script")
        key.refresh_from_db()
        assert token not in (key.hashed_key, key.lookup)
        assert key.hashed_key == ApiKey.hash_token(token)

    def test_the_token_carries_a_recognisable_prefix(self):
        """A leaked key is identifiable in a log or a paste."""
        _, token = ApiKey.generate(self.user, "x")
        assert token.startswith(ApiKey.TOKEN_PREFIX)

    def test_the_lookup_is_the_head_of_the_token(self):
        key, token = ApiKey.generate(self.user, "x")
        assert token.startswith(key.lookup)
        assert len(key.lookup) == ApiKey.LOOKUP_LENGTH

    def test_two_keys_never_share_a_token(self):
        _, first = ApiKey.generate(self.user, "one")
        _, second = ApiKey.generate(self.user, "two")
        assert first != second

    def test_an_unnamed_key_still_gets_a_name(self):
        """A key nobody can name is a key nobody dares revoke."""
        key, _ = ApiKey.generate(self.user, "   ")
        assert key.name

    def test_revoking_twice_keeps_the_first_date(self):
        """The date says when access ended, so a resubmit must not move it."""
        key, _ = ApiKey.generate(self.user, "x")
        key.revoke()
        first = key.revoked_at
        key.revoke()
        assert key.revoked_at == first


@pytest.mark.django_db
class TestResolveKey:
    def setup_method(self):
        self.user = User.objects.create_user(email="pro@example.com", pro_courtesy=True)
        self.key, self.token = ApiKey.generate(self.user, "x")

    def test_a_live_token_resolves(self):
        assert resolve_key(self.token) == self.key

    def test_a_revoked_token_stops_working(self):
        """Revoking is the answer to a leak, so it has to act at once."""
        self.key.revoke()
        assert resolve_key(self.token) is None

    def test_an_unknown_token_resolves_to_nothing(self):
        assert resolve_key("cc_not-a-real-key") is None

    def test_the_right_prefix_with_the_wrong_secret_is_refused(self):
        """The prefix finds the row; only the hash decides."""
        forged = self.key.lookup + "x" * 32
        assert resolve_key(forged) is None


class TestBearerToken:
    """Header parsing — no database."""

    class _Request:
        def __init__(self, value=None):
            self.headers = {"Authorization": value} if value is not None else {}

    def test_absent_header(self):
        assert bearer_token(self._Request()) is None

    def test_the_scheme_is_case_insensitive(self):
        assert bearer_token(self._Request("bearer abc")) == "abc"

    def test_another_scheme_is_not_a_token(self):
        assert bearer_token(self._Request("Basic abc")) is None

    def test_an_empty_token_is_no_token(self):
        assert bearer_token(self._Request("Bearer   ")) is None


@pytest.mark.django_db
class TestWhatTheApiAccepts:
    def setup_method(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="pro@example.com", password="pw", pro_courtesy=True
        )
        self.key, self.token = ApiKey.generate(self.user, "x")
        self.headers = {"authorization": f"Bearer {self.token}"}

    def test_a_browser_session_is_not_a_credential(self):
        """The API is exempt from the CSRF check, so it cannot trust a cookie.

        A signed-in Pro reader with no key is refused exactly as a stranger is.
        Nothing in the website calls this endpoint, so this costs no feature.
        """
        self.client.force_login(self.user)
        response = self.client.get('/api/history')
        assert response.status_code == 401

    def test_a_revoked_key_is_refused(self):
        self.key.revoke()
        response = self.client.get('/api/history', headers=self.headers)
        assert response.status_code == 401

    def test_a_refusal_never_says_whether_the_key_existed(self):
        """A wrong key and a revoked key answer the same, so neither confirms
        the other's existence to somebody guessing."""
        self.key.revoke()
        revoked = self.client.get('/api/history', headers=self.headers).json()
        unknown = self.client.get(
            '/api/history', headers={"authorization": "Bearer cc_nonsense"}
        ).json()
        assert revoked["error"] == unknown["error"]

    def test_a_deactivated_account_loses_its_keys(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        response = self.client.get('/api/history', headers=self.headers)
        assert response.status_code == 403

    def test_health_needs_no_key(self):
        assert self.client.get('/api/health').status_code == 200

    def test_use_is_recorded(self):
        """The stamp is what an operator reads before revoking a key."""
        assert self.key.last_used_at is None
        self.client.get('/api/history', headers=self.headers)
        self.key.refresh_from_db()
        assert self.key.last_used_at is not None

    def test_a_busy_key_does_not_write_on_every_call(self):
        """The stamp answers a question a minute cannot change the answer to."""
        self.client.get('/api/history', headers=self.headers)
        self.key.refresh_from_db()
        first = self.key.last_used_at

        self.client.get('/api/history', headers=self.headers)
        self.key.refresh_from_db()
        assert self.key.last_used_at == first

    def test_a_stale_stamp_is_refreshed(self):
        ApiKey.objects.filter(pk=self.key.pk).update(
            last_used_at=timezone.now() - timedelta(hours=2)
        )
        self.client.get('/api/history', headers=self.headers)
        self.key.refresh_from_db()
        assert self.key.last_used_at is not None
        assert timezone.now() - self.key.last_used_at < timedelta(minutes=1)

    def test_history_is_the_key_owners_history(self):
        """The key stands in for the account, so the reads are that account's."""
        SearchHistory.objects.create(user=self.user, query="guards", result_count=3)
        other = User.objects.create_user(email="other@example.com", pro_courtesy=True)
        SearchHistory.objects.create(user=other, query="stairs", result_count=1)

        results = self.client.get('/api/history', headers=self.headers).json()["results"]
        assert [row["query"] for row in results] == ["guards"]


@pytest.mark.django_db
class TestTheDailyAllowance:
    """An allowance on API searches, and on nothing else.

    Past it the search is **slowed, never refused** — a wall stopped a busy
    subscriber dead and cost a bulk copier only a day.  It does not stop
    somebody copying the corpus; see ``API_SEARCHES_BEFORE_THROTTLE`` for why
    nothing here does.  It makes a copy slow, attributable and visible, which
    is a different and achievable thing.
    """

    def setup_method(self):
        self.client = Client()
        self.user = User.objects.create_user(email="pro@example.com", pro_courtesy=True)
        self.key, self.token = ApiKey.generate(self.user, "x")
        self.headers = {"authorization": f"Bearer {self.token}"}

    def _fill(self, count, **kwargs):
        for _ in range(count):
            SearchHistory.objects.create(
                user=self.user,
                query="guards",
                source=SearchHistory.Source.API,
                **kwargs,
            )

    def test_the_search_still_runs_once_the_day_is_spent(self, monkeypatch):
        """The whole change: it waits, and then it answers."""
        self._fill(API_SEARCHES_BEFORE_THROTTLE)
        slept: list[float] = []
        monkeypatch.setattr("web.api.auth.time.sleep", slept.append)

        response = self.client.post(
            '/api/search',
            data=json.dumps({"query": "guards"}),
            content_type="application/json",
            headers=self.headers,
        )

        assert response.status_code != 429
        assert slept == [API_THROTTLE_STEP_SECONDS]

    def test_reading_the_editions_is_never_slowed(self, monkeypatch):
        """The allowance is on the cost, and a list of editions has none."""
        self._fill(API_SEARCHES_BEFORE_THROTTLE)
        slept: list[float] = []
        monkeypatch.setattr("web.api.auth.time.sleep", slept.append)

        assert self.client.get('/api/codes', headers=self.headers).status_code != 429
        assert slept == []

    def test_a_second_key_buys_no_second_allowance(self, monkeypatch):
        """The allowance belongs to the account, not to the credential."""
        self._fill(API_SEARCHES_BEFORE_THROTTLE)
        _, other = ApiKey.generate(self.user, "another")
        slept: list[float] = []
        monkeypatch.setattr("web.api.auth.time.sleep", slept.append)

        self.client.post(
            '/api/search',
            data=json.dumps({"query": "guards"}),
            content_type="application/json",
            headers={"authorization": f"Bearer {other}"},
        )

        assert slept == [API_THROTTLE_STEP_SECONDS]

    def test_reading_on_the_website_spends_nothing(self):
        """A subscriber's own reading is unlimited and must not be counted."""
        for _ in range(API_SEARCHES_BEFORE_THROTTLE):
            SearchHistory.objects.create(user=self.user, query="guards")

        assert searches_today(self.user) == 0

    def test_somebody_elses_searches_are_not_counted(self):
        other = User.objects.create_user(email="other@example.com", pro_courtesy=True)
        SearchHistory.objects.create(
            user=other, query="guards", source=SearchHistory.Source.API
        )

        assert searches_today(self.user) == 0

    def test_yesterday_does_not_count_against_today(self):
        self._fill(API_SEARCHES_BEFORE_THROTTLE)
        SearchHistory.objects.filter(user=self.user).update(
            timestamp=timezone.now() - timedelta(days=1)
        )

        assert searches_today(self.user) == 0


class TestHowLongTheWaitIs:
    """The curve, on its own. No database and no request.

    ``throttle_delay`` is pure, so the shape of the throttle is stated here
    rather than inferred from how a view behaved.
    """

    def test_inside_the_allowance_nothing_waits(self):
        assert throttle_delay(0) == 0
        assert throttle_delay(API_SEARCHES_BEFORE_THROTTLE - 1) == 0

    def test_the_first_search_past_the_line_waits_one_step(self):
        assert throttle_delay(API_SEARCHES_BEFORE_THROTTLE) == API_THROTTLE_STEP_SECONDS

    def test_the_wait_grows_with_the_overage(self):
        """A flat penalty is one a script plans around; a growing one is not."""
        first = throttle_delay(API_SEARCHES_BEFORE_THROTTLE)
        tenth = throttle_delay(API_SEARCHES_BEFORE_THROTTLE + 9)

        assert tenth > first

    def test_the_wait_stops_at_the_ceiling(self):
        """A request that outlives the gateway timeout is a 502 — a hard
        failure again, by accident.  The ceiling is what prevents that."""
        assert throttle_delay(API_SEARCHES_BEFORE_THROTTLE + 10_000) == (
            API_THROTTLE_MAX_SECONDS
        )


@pytest.mark.django_db
class TestTheOperatorNotice:
    """Nothing refuses a caller now, so a person reading the message is the
    control.  That makes the notice load-bearing rather than informational."""

    def setup_method(self):
        self.user = User.objects.create_user(email="heavy@example.com", pro_courtesy=True)

    def test_it_writes_one_record_and_one_message_a_day(self, settings, mailoutbox):
        settings.API_THROTTLE_NOTICE_EMAILS = ["rob@codechronicle.ca"]

        for _ in range(5):
            notify_api_throttle(self.user, used=250, delay=4.0)

        assert len(mailoutbox) == 1
        assert (
            EngagementEvent.objects.filter(
                user=self.user,
                event_type=EngagementEvent.EventType.API_THROTTLE,
            ).count()
            == 1
        )

    def test_the_message_names_the_account_and_the_count(self, settings, mailoutbox):
        settings.API_THROTTLE_NOTICE_EMAILS = ["rob@codechronicle.ca"]

        notify_api_throttle(self.user, used=250, delay=4.0)

        body = mailoutbox[0].body
        assert "heavy@example.com" in body
        assert "250" in body
        # It must not read as a refusal: nothing was withheld.
        assert "Nothing has been refused" in body

    def test_an_empty_recipient_list_still_records_the_event(self, settings, mailoutbox):
        """The record is the evidence; the message is only the alert.  A local
        run wants the second switched off and the first kept."""
        settings.API_THROTTLE_NOTICE_EMAILS = []

        notify_api_throttle(self.user, used=250, delay=4.0)

        assert mailoutbox == []
        assert EngagementEvent.objects.filter(user=self.user).count() == 1

    def test_a_broken_mail_host_never_breaks_the_search(self, settings, monkeypatch):
        """The caller is a paying subscriber whose request is valid."""
        settings.API_THROTTLE_NOTICE_EMAILS = ["rob@codechronicle.ca"]

        def explode(*args, **kwargs):
            raise RuntimeError("smtp is down")

        monkeypatch.setattr("telemetry.throttle_notice.send_mail", explode)

        notify_api_throttle(self.user, used=250, delay=4.0)  # must not raise

    def test_yesterdays_notice_does_not_silence_today(self):
        notify_api_throttle(self.user, used=250, delay=4.0)
        EngagementEvent.objects.filter(user=self.user).update(
            timestamp=timezone.now() - timedelta(days=1)
        )

        notify_api_throttle(self.user, used=250, delay=4.0)

        assert EngagementEvent.objects.filter(user=self.user).count() == 2
