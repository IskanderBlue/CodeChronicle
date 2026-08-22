"""Seats: who belongs to which organization, and how a person gets a seat.

The models hold the reads (``Organization.seats_free`` and the rest).  This
module holds the operations, because each of them is a decision the card
records and none of them belongs to one view.

Three rules run through everything here:

* **An organization is created at checkout, not at signup.**  A free reader
  has no organization row.  ``organization_for_checkout`` is the only place
  that makes one for a person buying alone.
* **The seat check runs where a person is added** — at acceptance, which is
  the moment a seat is really taken.  ``accept_invite`` is that place.
* **A person keeps their own login.**  Nothing here creates or renames an
  account.  A seat joins an account that the person made themselves.
"""

from __future__ import annotations

from coloured_logger import Logger
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from core.models import Invite, Membership, Organization, User

logger = Logger(__name__)


def team_memberships_enabled() -> bool:
    """Whether a signed-in reader's team memberships are honoured on screen.

    **A development switch, and an interface one only.**  With it off, the
    product behaves as though the reader belonged to no firm: the settings
    page draws no team panel, and the pricing page shows Team as something to
    buy rather than as the current plan.  That is what makes both states
    reachable without creating and destroying an organization each time.

    Two things it deliberately does not do:

    * **It does not hide the Team column, or stop a firm buying seats.**  The
      feature stays on sale in every state; only this reader's membership is
      set aside.
    * **It does not revoke access.**  The gate is
      ``User.has_active_subscription``, and this is not that gate.  A switch
      that locked out a paying member would be a gate wearing a switch's
      clothes.

    Set ``TEAM_MEMBERSHIPS_ENABLED=False`` in the environment.  On by default.
    """
    return bool(getattr(settings, "TEAM_MEMBERSHIPS_ENABLED", True))


class SeatError(Exception):
    """No seat is available, or the invitation cannot be accepted."""


def access_membership(user: User) -> Membership | None:
    """The membership that pays for this user, or ``None``.

    A person can belong to two organizations — their own and their firm's —
    so this answers with the first one that is both paid and access-granting.
    Used where the interface needs to name the plan, never as the gate itself:
    the gate is ``User.has_active_subscription``.  That is what lets the
    development switch below answer ``None`` here without taking anybody's
    access away.
    """
    if not team_memberships_enabled():
        return None
    for membership in user.memberships.filter(role__in=Membership.SEAT_ROLES):
        if membership.organization.has_active_subscription:
            return membership
    return None


def administered_organizations(user: User) -> list[Organization]:
    """Organizations this user may manage.

    A billing-only membership manages without reading, which is the whole
    reason that role exists.
    """
    if not team_memberships_enabled():
        return []
    return [
        membership.organization
        for membership in user.memberships.filter(role__in=Membership.ADMIN_ROLES)
    ]


def personal_organization(user: User) -> Organization | None:
    """The organization this user owns alone, if they have one."""
    for membership in user.memberships.filter(role=Membership.Role.ADMIN):
        if membership.organization.is_personal:
            return membership.organization
    return None


@transaction.atomic
def organization_for_checkout(user: User, *, name: str = "", email: str = "") -> Organization:
    """The organization that a checkout will bill, made if it is not there.

    Somebody buying for themselves gets an organization of one, named after
    them.  They never see the word: ``Organization.is_personal`` is what the
    interface asks before it says anything about a firm.

    Re-uses an existing personal organization rather than making a second, so
    a reader who cancelled and came back does not end with two billing
    entities and one confused invoice.
    """
    existing = personal_organization(user)
    if existing is not None and not name:
        return existing

    organization = Organization.objects.create(
        name=(name.strip() or user.email)[:200],
        email=email.strip() or user.email,
    )
    Membership.objects.create(
        organization=organization, user=user, role=Membership.Role.ADMIN
    )
    return organization


@transaction.atomic
def invite_member(
    organization: Organization,
    email: str,
    role: str,
    invited_by: User | None = None,
) -> tuple[Invite, str]:
    """Ask somebody to take a seat.  Returns the invitation and its one token.

    The seat check runs here as well as at acceptance, and the two ask
    different questions.  Here it counts the seats already promised, so an
    admin cannot send ten invitations against three seats and leave seven
    people to meet a refusal they did nothing to earn.  At acceptance it
    counts the seats actually taken, which is the number that matters.

    A billing-only invitation skips the check, because that role takes no seat.
    """
    email = email.strip().lower()
    if not email:
        raise SeatError("An invitation needs an email address.")

    if Membership.objects.filter(
        organization=organization, user__email__iexact=email
    ).exists():
        raise SeatError(f"{email} is already in this organization.")

    if organization.invites.filter(
        email=email, accepted_at__isnull=True, revoked_at__isnull=True
    ).exists():
        raise SeatError(f"{email} already has an open invitation.")

    if role in Membership.SEAT_ROLES:
        promised = organization.invites.filter(
            accepted_at__isnull=True,
            revoked_at__isnull=True,
            role__in=Membership.SEAT_ROLES,
            expires_at__gt=timezone.now(),
        ).count()
        if organization.seats_free <= promised:
            raise SeatError(
                "Every seat is taken or promised. "
                "Add a seat before you invite somebody else."
            )

    return Invite.generate(organization, email, role, invited_by)


@transaction.atomic
def accept_invite(invite: Invite, user: User) -> Membership:
    """Take the seat.  This is where the seat check binds.

    Refuses when the address does not match, because an invitation is
    addressed to a person and a forwarded link is not a transfer.  Refuses
    when no seat is free, because the count on the invoice is the count that
    may read.

    The row is locked while the count is read, so two people accepting at the
    same moment cannot both take the last seat.
    """
    organization = Organization.objects.select_for_update().get(pk=invite.organization_id)

    if invite.email.lower() != user.email.lower():
        raise SeatError(
            f"This invitation is for {invite.email}. "
            "Sign in with that address to take the seat."
        )
    if not invite.is_open:
        raise SeatError("This invitation has been used, withdrawn, or has expired.")

    existing = Membership.objects.filter(organization=organization, user=user).first()
    if existing is not None:
        invite.accepted_at = timezone.now()
        invite.save(update_fields=["accepted_at"])
        return existing

    if invite.role in Membership.SEAT_ROLES and organization.seats_free < 1:
        raise SeatError(
            "There is no free seat in this organization. "
            "Ask an administrator to add one."
        )

    membership = Membership.objects.create(
        organization=organization, user=user, role=invite.role
    )
    invite.accepted_at = timezone.now()
    invite.save(update_fields=["accepted_at"])
    return membership


def remove_member(membership: Membership) -> None:
    """End a seat.

    The account survives, drops to free tier, and keeps its own history.  A
    person's searches are that person's work, and they do not belong to the
    firm that paid for the seat.
    """
    membership.delete()


def send_invite_email(invite: Invite, accept_url: str) -> None:
    """Send the one copy of the link.

    Never raises.  The invitation already exists when this runs, so a mail
    host that is slow must not lose the row as well as the message — the admin
    can re-send.  Same reasoning as ``accounts.signals.signup_notice``.
    """
    inviter = invite.invited_by.email if invite.invited_by else "An administrator"
    body = "\n".join(
        [
            f"{inviter} has given you a seat on CodeChronicle "
            f"for {invite.organization.name}.",
            "",
            "Open this link to take it:",
            accept_url,
            "",
            f"The link works until {invite.expires_at:%d %B %Y}, "
            f"and only for {invite.email}.",
        ]
    )
    try:
        send_mail(
            subject=f"Your CodeChronicle seat at {invite.organization.name}",
            message=body,
            from_email=None,  # DEFAULT_FROM_EMAIL
            recipient_list=[invite.email],
            fail_silently=False,
        )
    except Exception as exc:  # noqa: BLE001 — a lost mail must not lose the invite
        logger.error("Could not send the invitation to %s: %s", invite.email, exc)
