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


def test_dashboard_campaign_id_out_of_int4_range_is_422_not_500(client):
    """Regression: campaign_id is a plain Postgres INTEGER (4-byte)
    primary key. Before this was bounded via FastAPI's Query(le=...), an
    absurdly large campaign_id crashed with an unhandled 500
    (psycopg.errors.NumericValueOutOfRange) instead of a clean 4xx.
    """
    response = client.get("/dashboard?campaign_id=99999999999999999999")
    assert response.status_code == 422


def test_dashboard_view_renders_html_with_chart_data(client, db_session, make_contact, make_campaign):
    """The funnel trace's "x" values are asserted exactly, in
    PRIMARY_STAGES order (pending, sent, opened, clicked, replied) -- just
    checking the literal word "replied" appears would be tautological,
    since that stage label is emitted unconditionally regardless of
    whether its count was ever wired through correctly.
    """
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
    assert '"x":[0,0,0,0,1]' in response.text


def test_dashboard_view_scopes_to_one_campaign(client, db_session, make_contact, make_campaign):
    campaign_a = make_campaign("PN-D4A", "D4A")
    campaign_b = make_campaign("PN-D4B", "D4B")
    db_session.add(CampaignContact(
        campaign_id=campaign_a.id,
        contact_id=make_contact("view-scope-a@example.com").id,
        status=AssignmentStatus.CLICKED,
    ))
    db_session.add(CampaignContact(
        campaign_id=campaign_b.id,
        contact_id=make_contact("view-scope-b@example.com").id,
        status=AssignmentStatus.CLICKED,
    ))
    db_session.commit()

    response = client.get(f"/dashboard/view?campaign_id={campaign_a.id}")
    assert response.status_code == 200
    # clicked=1, everything else 0, for campaign_a alone.
    assert '"x":[0,0,0,1,0]' in response.text


def test_dashboard_view_renders_with_no_data(client):
    """The one shape not covered by the other view tests: an all-zero
    funnel. go.Funnel computes stage-over-stage percentages internally,
    so an all-zero input is the case most likely to trip a future
    divide-by-zero/empty-data edge case.
    """
    response = client.get("/dashboard/view")
    assert response.status_code == 200
    assert '"x":[0,0,0,0,0]' in response.text


def test_dashboard_view_unknown_campaign_is_404(client):
    response = client.get("/dashboard/view?campaign_id=999999")
    assert response.status_code == 404


def test_dashboard_view_campaign_id_out_of_int4_range_is_422_not_500(client):
    response = client.get("/dashboard/view?campaign_id=99999999999999999999")
    assert response.status_code == 422
