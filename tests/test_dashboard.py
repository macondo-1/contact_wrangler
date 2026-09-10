"""Phase 6 regression tests for GET /dashboard and GET /dashboard/view
(Task 3.11 design, Task 6.2 Plotly view).
"""

from contact_wrangler.models import AssignmentStatus, CampaignContact


def test_dashboard_returns_all_stages_zero_filled_with_no_data(client):
    response = client.get("/dashboard")
    assert response.status_code == 200
    body = response.json()
    assert [stage["status"] for stage in body] == [
        "pending", "sent", "opened", "clicked", "replied",
        "bounced", "unsubscribed", "excluded",
    ]
    assert all(stage["count"] == 0 for stage in body)


def test_dashboard_counts_reflect_assignment_statuses(client, db_session, make_contact, make_campaign):
    campaign = make_campaign("PN-D1", "D1")
    db_session.add(CampaignContact(
        campaign_id=campaign.id,
        contact_id=make_contact("d1@example.com").id,
        status=AssignmentStatus.SENT,
    ))
    db_session.add(CampaignContact(
        campaign_id=campaign.id,
        contact_id=make_contact("d2@example.com").id,
        status=AssignmentStatus.SENT,
    ))
    db_session.add(CampaignContact(
        campaign_id=campaign.id,
        contact_id=make_contact("d3@example.com").id,
        status=AssignmentStatus.BOUNCED,
    ))
    db_session.commit()

    counts = {s["status"]: s["count"] for s in client.get("/dashboard").json()}
    assert counts["sent"] == 2
    assert counts["bounced"] == 1
    assert counts["pending"] == 0


def test_dashboard_scopes_to_one_campaign(client, db_session, make_contact, make_campaign):
    campaign_a = make_campaign("PN-D2A", "D2A")
    campaign_b = make_campaign("PN-D2B", "D2B")
    db_session.add(CampaignContact(
        campaign_id=campaign_a.id,
        contact_id=make_contact("scope-a@example.com").id,
        status=AssignmentStatus.SENT,
    ))
    db_session.add(CampaignContact(
        campaign_id=campaign_b.id,
        contact_id=make_contact("scope-b@example.com").id,
        status=AssignmentStatus.SENT,
    ))
    db_session.commit()

    counts = {
        s["status"]: s["count"]
        for s in client.get(f"/dashboard?campaign_id={campaign_a.id}").json()
    }
    assert counts["sent"] == 1


def test_dashboard_unknown_campaign_is_404(client):
    response = client.get("/dashboard?campaign_id=999999")
    assert response.status_code == 404


def test_dashboard_view_renders_html_with_chart_data(client, db_session, make_contact, make_campaign):
    campaign = make_campaign("PN-D3", "D3")
    db_session.add(CampaignContact(
        campaign_id=campaign.id,
        contact_id=make_contact("view@example.com").id,
        status=AssignmentStatus.REPLIED,
    ))
    db_session.commit()

    response = client.get("/dashboard/view")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "funnel" in response.text
    assert "replied" in response.text


def test_dashboard_view_unknown_campaign_is_404(client):
    response = client.get("/dashboard/view?campaign_id=999999")
    assert response.status_code == 404
