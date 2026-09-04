"""Task 1.8 -- the rolling eligibility-window (cooldown) query.

This module deliberately splits into TWO functions, checked at two different
points in time, rather than one combined "eligibility" check:

1. `eligible_contacts_for_campaign` -- ASSIGNMENT time. Decides who should
   get a new campaign_contacts row created for this campaign at all. Checks
   baseline contactability (active, opted in, has an email, not known-
   invalid) and that they aren't already assigned to *this* campaign.

2. `sendable_assignments_for_campaign` -- SEND time. Decides which already-
   assigned (PENDING) contacts are safe to actually email *right now*. This
   is where the cooldown window belongs.

Why cooldown can't live in the assignment-time function: cooldown is time-
dependent -- nobody updates a row when 30 days pass, time just passes. If
cooldown were checked only at assignment time, a contact who happens to be
mid-cooldown at that moment would be skipped and never reconsidered once
their cooldown clears (unless something re-runs assignment later, which
isn't how this is meant to work). Checking cooldown at send time instead
means a contact can be assigned once, sit as PENDING, and become sendable
automatically the moment their cooldown expires -- no re-assignment step
needed.

Why "already assigned" is scoped to the *same* campaign only, not global:
deliberately NOT exclusive across campaigns. The same contact can be
eligible for, and assigned to, multiple campaigns at once. Only one campaign
will actually get to send to them first; the other's assignment simply waits
-- the global send-time cooldown (below) naturally arbitrates who sends when,
without needing a separate cross-campaign locking mechanism (which would risk
a contact being stuck forever if the first campaign's assignment never
resolves).

Cooldown itself IS global across campaigns: a contact sent something for
Campaign A is also excluded from being sent to for Campaign B while inside
the cooldown window -- that's what makes the staggered-send behavior above
work correctly, rather than both campaigns racing to send simultaneously.

The supporting index is campaign_contacts(contact_id, last_sent_at)
(Task 1.7) -- contact_id as an equality lookup, last_sent_at as a range scan
on that same index, exactly the access pattern the correlated EXISTS
subqueries below produce.

Neither function is wired to an endpoint yet (Phase 3 does that) -- both
only build a Select statement. Callers execute it themselves, e.g.:

    contacts = session.execute(eligible_contacts_for_campaign(42)).scalars().all()
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import Select, select
from sqlalchemy.orm import aliased

from contact_wrangler.models import AssignmentStatus, CampaignContact, Contact, EmailValidation


def _baseline_contactable_filters():
    """Shared baseline contactability conditions, reused at both assignment
    time and send time (a contact could opt out or bounce between the two).
    """
    return (
        Contact.is_active.is_(True),
        Contact.is_opt_in.is_(True),
        Contact.email.is_not(None),
        # NULL-safe "not INVALID": a plain `!=` would silently drop contacts
        # whose email_validation is NULL (never checked), since NULL != X is
        # NULL in SQL, not True. IS DISTINCT FROM treats NULL correctly as
        # "not equal to INVALID", so unchecked contacts stay eligible.
        Contact.email_validation.is_distinct_from(EmailValidation.INVALID),
    )


def eligible_contacts_for_campaign(campaign_id: int) -> Select:
    """Build (not execute) a query for contacts to newly assign to `campaign_id`.

    A contact is eligible when:
      - baseline contactable (see _baseline_contactable_filters)
      - not already assigned to this specific campaign

    Deliberately no cooldown check here -- see module docstring.
    """
    already_assigned = (
        select(CampaignContact.id)
        .where(
            CampaignContact.contact_id == Contact.id,
            CampaignContact.campaign_id == campaign_id,
        )
        .exists()
    )

    return select(Contact).where(
        *_baseline_contactable_filters(),
        ~already_assigned,
    )


def sendable_assignments_for_campaign(
    campaign_id: int,
    cooldown_days: int = 30,
) -> Select:
    """Build (not execute) a query for PENDING assignments safe to send now.

    Returns CampaignContact rows (not bare Contact rows) -- sending needs the
    assignment row itself, to update its status/last_sent_at afterward.

    A PENDING assignment is sendable when:
      - the contact still passes baseline contactability (re-checked --
        state may have changed since assignment)
      - the contact hasn't been sent anything, for ANY campaign, within the
        last `cooldown_days` days (the global cooldown)
    """
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=cooldown_days)

    # Aliased so this is unambiguously a *separate* scan over the contact's
    # other assignments -- without the alias, SQLAlchemy's auto-correlation
    # collapses this subquery's CampaignContact into the outer query's (which
    # also selects from CampaignContact), leaving it with no FROM clause at all.
    OtherAssignment = aliased(CampaignContact)

    recently_contacted = (
        select(OtherAssignment.id)
        .where(
            OtherAssignment.contact_id == Contact.id,
            # No explicit `is_not(None)` needed here: `last_sent_at > cutoff`
            # already evaluates to NULL (excluded) when last_sent_at is NULL,
            # so a never-sent contact naturally fails to match on its own.
            OtherAssignment.last_sent_at > cutoff,
        )
        .exists()
    )

    return (
        select(CampaignContact)
        .join(Contact, Contact.id == CampaignContact.contact_id)
        .where(
            CampaignContact.campaign_id == campaign_id,
            CampaignContact.status == AssignmentStatus.PENDING,
            *_baseline_contactable_filters(),
            ~recently_contacted,
        )
    )
