"""Where an administrator runs a firm's seats, and where a person takes one.

Every write here answers to ``core.teams``, which owns the seat rules.  These
views own the HTTP: who is allowed to press the control, and what the reader
is told when the answer is no.

Two shapes of refusal, and they are different on purpose:

* **A control somebody may not use is not drawn.**  A member sees no invite
  form, because the settings page asks for an administering membership before
  it includes the panel.
* **A control somebody may use, that cannot succeed right now, says why.**  A
  seat that is not free is a fact about the subscription, not about the
  person, and hiding it would leave an administrator guessing.
"""

from __future__ import annotations

from typing import cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import Invite, Membership, Organization, User
from core.teams import (
    SeatError,
    accept_invite,
    invite_member,
    personal_organization,
    remove_member,
    send_invite_email,
)
from core.views.settings_nav import TEAM_SECTION, settings_redirect


def _administered(user: User, organization_pk: int) -> Organization:
    """The organization, if this user administers it.  A 404 otherwise.

    A 404 rather than a 403: an id somebody guessed must not confirm that the
    organization exists.
    """
    membership = get_object_or_404(
        Membership,
        organization_id=organization_pk,
        user=user,
        role__in=Membership.ADMIN_ROLES,
    )
    return membership.organization


@login_required
@require_POST
def invite_to_team(request: HttpRequest, pk: int) -> HttpResponse:
    """Send one invitation."""
    user = cast(User, request.user)
    organization = _administered(user, pk)

    role = request.POST.get("role") or Membership.Role.MEMBER
    if role not in Membership.Role.values:
        role = Membership.Role.MEMBER

    try:
        invite, token = invite_member(
            organization, request.POST.get("email") or "", role, invited_by=user
        )
    except SeatError as exc:
        messages.error(request, str(exc))
        return settings_redirect(TEAM_SECTION)

    send_invite_email(
        invite,
        request.build_absolute_uri(reverse("core:accept_invite", args=[token])),
    )
    messages.success(request, f"Invitation sent to {invite.email}.")
    return settings_redirect(TEAM_SECTION)


@login_required
@require_POST
def revoke_invite(request: HttpRequest, pk: int) -> HttpResponse:
    """Withdraw an invitation that nobody has accepted.

    The row stays, because it is the record that somebody was asked.
    """
    user = cast(User, request.user)
    invite = get_object_or_404(Invite, pk=pk, accepted_at__isnull=True)
    _administered(user, invite.organization_id)

    if invite.revoked_at is None:
        invite.revoked_at = timezone.now()
        invite.save(update_fields=["revoked_at"])
    messages.success(request, f"The invitation to {invite.email} is withdrawn.")
    return settings_redirect(TEAM_SECTION)


@login_required
@require_POST
def remove_from_team(request: HttpRequest, pk: int) -> HttpResponse:
    """End somebody's seat.

    The account survives and drops to free tier, keeping its own history.  An
    administrator cannot remove the last administrator, because an
    organization nobody can manage is one nobody can cancel either.
    """
    user = cast(User, request.user)
    membership = get_object_or_404(Membership, pk=pk)
    organization = _administered(user, membership.organization_id)

    if membership.is_admin:
        remaining = organization.memberships.filter(
            role__in=Membership.ADMIN_ROLES
        ).exclude(pk=membership.pk)
        if not remaining.exists():
            messages.error(
                request,
                "This is the only administrator. "
                "Make somebody else an administrator first.",
            )
            return settings_redirect(TEAM_SECTION)

    removed = membership.user.email
    remove_member(membership)
    messages.success(request, f"{removed} no longer has a seat.")
    return settings_redirect(TEAM_SECTION)


@login_required
def accept_invite_view(request: HttpRequest, token: str) -> HttpResponse:
    """Take a seat, after the person has seen what they are joining.

    A GET shows what the invitation is for and asks; the POST takes the seat.
    A link that acted on being opened would let a mail scanner spend the seat
    before the person ever read the message.

    ``login_required`` sends somebody with no account to sign in or sign up
    first, and allauth returns them here.  So the invitation never creates an
    account: a person keeps their own login, which is what makes the reading
    record theirs.
    """
    user = cast(User, request.user)
    invite = Invite.open_for_token(token)

    if invite is None:
        return render(
            request,
            "team_invite.html",
            {"invite": None, "problem": "This invitation link is not valid any more."},
            status=404,
        )

    if invite.email.lower() != user.email.lower():
        return render(
            request,
            "team_invite.html",
            {
                "invite": invite,
                "problem": (
                    f"This invitation is for {invite.email}, "
                    f"and you are signed in as {user.email}."
                ),
            },
            status=403,
        )

    # The double-subscription case.  Somebody who already pays for themselves
    # must not go on paying while a seat covers them, and the decision to end
    # a paid subscription is theirs to make with a click.
    own = personal_organization(user)
    pays_already = own is not None and own.has_active_subscription

    if request.method != "POST":
        return render(
            request,
            "team_invite.html",
            {"invite": invite, "problem": None, "pays_already": pays_already},
        )

    try:
        accept_invite(invite, user)
    except SeatError as exc:
        return render(
            request,
            "team_invite.html",
            {"invite": invite, "problem": str(exc)},
            status=409,
        )

    messages.success(
        request, f"You have a seat at {invite.organization.name}."
    )
    if pays_already:
        messages.info(
            request,
            "You are also paying for CodeChronicle yourself. "
            "Open Manage billing to end that subscription.",
        )
    return settings_redirect(TEAM_SECTION)
