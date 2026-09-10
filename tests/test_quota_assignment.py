"""Task 5.5: POST /campaigns/{id}/contacts (quota-aware assignment) tests
(Task 3.8 design).
"""

from contact_wrangler.models import Campaign, CampaignQuota, CampaignStatus, Contact


def _make_contact(db_session, email, **overrides):
    defaults = {"email": email, "is_active": True, "is_opt_in": True}
    defaults.update(overrides)
    contact = Contact(**defaults)
    db_session.add(contact)
    db_session.flush()
    return contact


def _make_campaign(db_session, project_number, name, **overrides):
    defaults = {"project_number": project_number, "name": name}
    defaults.update(overrides)
    campaign = Campaign(**defaults)
    db_session.add(campaign)
    db_session.flush()
    return campaign


def _make_quota(db_session, campaign_id, target_count, dimension="country", dimension_value="USA"):
    quota = CampaignQuota(
        campaign_id=campaign_id,
        dimension=dimension,
        dimension_value=dimension_value,
        target_count=target_count,
    )
    db_session.add(quota)
    db_session.flush()
    return quota


def test_assignment_under_quota_is_not_flagged(client, db_session):
    contact = _make_contact(db_session, "under@example.com")
    campaign = _make_campaign(db_session, "PN-Q1", "Q1")
    quota = _make_quota(db_session, campaign.id, target_count=5)
    db_session.commit()

    r = client.post(
        f"/campaigns/{campaign.id}/contacts",
        json={"contact_id": contact.id, "quota_id": quota.id},
    )
    assert r.status_code == 201
    assert r.json()["quota_exceeded"] is False


def test_assignment_at_quota_is_flagged_but_accepted(client, db_session):
    campaign = _make_campaign(db_session, "PN-Q2", "Q2")
    quota = _make_quota(db_session, campaign.id, target_count=1)
    contact_a = _make_contact(db_session, "quota-a@example.com")
    contact_b = _make_contact(db_session, "quota-b@example.com")
    db_session.commit()

    r1 = client.post(
        f"/campaigns/{campaign.id}/contacts",
        json={"contact_id": contact_a.id, "quota_id": quota.id},
    )
    assert r1.status_code == 201
    assert r1.json()["quota_exceeded"] is False

    r2 = client.post(
        f"/campaigns/{campaign.id}/contacts",
        json={"contact_id": contact_b.id, "quota_id": quota.id},
    )
    assert r2.status_code == 201
    assert r2.json()["quota_exceeded"] is True


def test_completed_campaign_rejects_assignment(client, db_session):
    contact = _make_contact(db_session, "completed@example.com")
    campaign = _make_campaign(
        db_session, "PN-Q3", "Q3", status=CampaignStatus.COMPLETED
    )
    db_session.commit()

    r = client.post(
        f"/campaigns/{campaign.id}/contacts", json={"contact_id": contact.id}
    )
    assert r.status_code == 409


def test_non_contactable_contact_is_rejected(client, db_session):
    contact = _make_contact(db_session, "optout@example.com", is_opt_in=False)
    campaign = _make_campaign(db_session, "PN-Q4", "Q4")
    db_session.commit()

    r = client.post(
        f"/campaigns/{campaign.id}/contacts", json={"contact_id": contact.id}
    )
    assert r.status_code == 400


def test_duplicate_assignment_is_rejected(client, db_session):
    contact = _make_contact(db_session, "dup-assign@example.com")
    campaign = _make_campaign(db_session, "PN-Q5", "Q5")
    db_session.commit()

    r1 = client.post(
        f"/campaigns/{campaign.id}/contacts", json={"contact_id": contact.id}
    )
    assert r1.status_code == 201

    r2 = client.post(
        f"/campaigns/{campaign.id}/contacts", json={"contact_id": contact.id}
    )
    assert r2.status_code == 409


def test_quota_from_different_campaign_is_rejected(client, db_session):
    contact = _make_contact(db_session, "wrong-quota@example.com")
    campaign_a = _make_campaign(db_session, "PN-Q6A", "Q6A")
    campaign_b = _make_campaign(db_session, "PN-Q6B", "Q6B")
    quota_a = _make_quota(db_session, campaign_a.id, target_count=5)
    db_session.commit()

    r = client.post(
        f"/campaigns/{campaign_b.id}/contacts",
        json={"contact_id": contact.id, "quota_id": quota_a.id},
    )
    assert r.status_code == 400
