"""Task 5.4: eligibility-window (cooldown) tests (Task 1.8 design).

Boundary margins are deliberately generous (an hour on either side of the
cutoff, not the literal instant) -- the query and this test each compute
`now()` independently a few milliseconds apart, so asserting behavior at
the exact boundary would be flaky, not a real test of the boundary logic.
"""

from datetime import datetime, timedelta, timezone

from contact_wrangler.eligibility import (
    eligible_contacts_for_campaign,
    sendable_assignments_for_campaign,
)
from contact_wrangler.models import AssignmentStatus, Campaign, CampaignContact, Contact


def _make_contact(db_session, email, **overrides):
    defaults = {"email": email, "is_active": True, "is_opt_in": True}
    defaults.update(overrides)
    contact = Contact(**defaults)
    db_session.add(contact)
    db_session.flush()
    return contact


def _make_campaign(db_session, project_number, name):
    campaign = Campaign(project_number=project_number, name=name)
    db_session.add(campaign)
    db_session.flush()
    return campaign


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def test_contact_within_cooldown_is_not_sendable(db_session):
    contact = _make_contact(db_session, "cooldown@example.com")
    campaign = _make_campaign(db_session, "PN-1", "C1")
    db_session.add(CampaignContact(
        campaign_id=campaign.id, contact_id=contact.id,
        status=AssignmentStatus.PENDING, last_sent_at=_now() - timedelta(days=5),
    ))
    db_session.commit()

    result = db_session.execute(
        sendable_assignments_for_campaign(campaign.id, cooldown_days=30)
    ).scalars().all()
    assert result == []


def test_contact_outside_cooldown_is_sendable(db_session):
    contact = _make_contact(db_session, "clear@example.com")
    campaign = _make_campaign(db_session, "PN-2", "C2")
    db_session.add(CampaignContact(
        campaign_id=campaign.id, contact_id=contact.id,
        status=AssignmentStatus.PENDING, last_sent_at=_now() - timedelta(days=31),
    ))
    db_session.commit()

    result = db_session.execute(
        sendable_assignments_for_campaign(campaign.id, cooldown_days=30)
    ).scalars().all()
    assert len(result) == 1
    assert result[0].contact_id == contact.id


def test_contact_never_sent_is_sendable(db_session):
    contact = _make_contact(db_session, "never@example.com")
    campaign = _make_campaign(db_session, "PN-3", "C3")
    db_session.add(CampaignContact(
        campaign_id=campaign.id, contact_id=contact.id, status=AssignmentStatus.PENDING,
    ))
    db_session.commit()

    result = db_session.execute(
        sendable_assignments_for_campaign(campaign.id, cooldown_days=30)
    ).scalars().all()
    assert len(result) == 1


def test_cooldown_is_global_across_campaigns(db_session):
    contact = _make_contact(db_session, "global@example.com")
    campaign_a = _make_campaign(db_session, "PN-A", "A")
    campaign_b = _make_campaign(db_session, "PN-B", "B")

    # Sent something for campaign A recently...
    db_session.add(CampaignContact(
        campaign_id=campaign_a.id, contact_id=contact.id,
        status=AssignmentStatus.SENT, last_sent_at=_now() - timedelta(days=2),
    ))
    # ...and separately assigned (not yet sent) to campaign B.
    db_session.add(CampaignContact(
        campaign_id=campaign_b.id, contact_id=contact.id, status=AssignmentStatus.PENDING,
    ))
    db_session.commit()

    # Should NOT be sendable for B either -- cooldown is global, not per-campaign.
    result = db_session.execute(
        sendable_assignments_for_campaign(campaign_b.id, cooldown_days=30)
    ).scalars().all()
    assert result == []


def test_assignment_time_eligibility_ignores_cooldown(db_session):
    """eligible_contacts_for_campaign (assignment-time) has deliberately no
    cooldown check -- a contact recently contacted for another campaign
    should still be eligible to be newly ASSIGNED (not yet sent) elsewhere.
    """
    contact = _make_contact(db_session, "assign-ok@example.com")
    campaign_a = _make_campaign(db_session, "PN-C", "C")
    campaign_b = _make_campaign(db_session, "PN-D", "D")
    db_session.add(CampaignContact(
        campaign_id=campaign_a.id, contact_id=contact.id,
        status=AssignmentStatus.SENT, last_sent_at=_now() - timedelta(days=1),
    ))
    db_session.commit()

    result = db_session.execute(eligible_contacts_for_campaign(campaign_b.id)).scalars().all()
    assert any(c.id == contact.id for c in result)


def test_boundary_just_outside_cooldown_is_sendable(db_session):
    contact = _make_contact(db_session, "boundary-out@example.com")
    campaign = _make_campaign(db_session, "PN-E", "E")
    db_session.add(CampaignContact(
        campaign_id=campaign.id, contact_id=contact.id, status=AssignmentStatus.PENDING,
        last_sent_at=_now() - timedelta(days=30, hours=1),
    ))
    db_session.commit()

    result = db_session.execute(
        sendable_assignments_for_campaign(campaign.id, cooldown_days=30)
    ).scalars().all()
    assert len(result) == 1


def test_boundary_just_inside_cooldown_is_not_sendable(db_session):
    contact = _make_contact(db_session, "boundary-in@example.com")
    campaign = _make_campaign(db_session, "PN-F", "F")
    db_session.add(CampaignContact(
        campaign_id=campaign.id, contact_id=contact.id, status=AssignmentStatus.PENDING,
        last_sent_at=_now() - timedelta(days=29, hours=23),
    ))
    db_session.commit()

    result = db_session.execute(
        sendable_assignments_for_campaign(campaign.id, cooldown_days=30)
    ).scalars().all()
    assert result == []
