"""Task 5.5: POST /campaigns/{id}/contacts (quota-aware assignment) tests
(Task 3.8 design).
"""

from contact_wrangler.models import CampaignQuota, CampaignStatus


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


def test_assignment_under_quota_is_not_flagged(client, db_session, make_contact, make_campaign):
    contact = make_contact("under@example.com")
    campaign = make_campaign("PN-Q1", "Q1")
    quota = _make_quota(db_session, campaign.id, target_count=5)
    db_session.commit()

    r = client.post(
        f"/campaigns/{campaign.id}/contacts",
        json={"contact_id": contact.id, "quota_id": quota.id},
    )
    assert r.status_code == 201
    assert r.json()["quota_exceeded"] is False


def test_assignment_at_quota_is_flagged_but_accepted(client, db_session, make_contact, make_campaign):
    campaign = make_campaign("PN-Q2", "Q2")
    quota = _make_quota(db_session, campaign.id, target_count=1)
    contact_a = make_contact("quota-a@example.com")
    contact_b = make_contact("quota-b@example.com")
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


def test_completed_campaign_rejects_assignment(client, db_session, make_contact, make_campaign):
    contact = make_contact("completed@example.com")
    campaign = make_campaign("PN-Q3", "Q3", status=CampaignStatus.COMPLETED)
    db_session.commit()

    r = client.post(
        f"/campaigns/{campaign.id}/contacts", json={"contact_id": contact.id}
    )
    assert r.status_code == 409


def test_non_contactable_contact_is_rejected(client, db_session, make_contact, make_campaign):
    contact = make_contact("optout@example.com", is_opt_in=False)
    campaign = make_campaign("PN-Q4", "Q4")
    db_session.commit()

    r = client.post(
        f"/campaigns/{campaign.id}/contacts", json={"contact_id": contact.id}
    )
    assert r.status_code == 400


def test_duplicate_assignment_is_rejected(client, db_session, make_contact, make_campaign):
    contact = make_contact("dup-assign@example.com")
    campaign = make_campaign("PN-Q5", "Q5")
    db_session.commit()

    r1 = client.post(
        f"/campaigns/{campaign.id}/contacts", json={"contact_id": contact.id}
    )
    assert r1.status_code == 201

    r2 = client.post(
        f"/campaigns/{campaign.id}/contacts", json={"contact_id": contact.id}
    )
    assert r2.status_code == 409


def test_quota_from_different_campaign_is_rejected(client, db_session, make_contact, make_campaign):
    contact = make_contact("wrong-quota@example.com")
    campaign_a = make_campaign("PN-Q6A", "Q6A")
    campaign_b = make_campaign("PN-Q6B", "Q6B")
    quota_a = _make_quota(db_session, campaign_a.id, target_count=5)
    db_session.commit()

    r = client.post(
        f"/campaigns/{campaign_b.id}/contacts",
        json={"contact_id": contact.id, "quota_id": quota_a.id},
    )
    assert r.status_code == 400
