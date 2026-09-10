import plotly.graph_objects as go
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from plotly.subplots import make_subplots
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from contact_wrangler.db import get_db
from contact_wrangler.models import AssignmentStatus, Campaign, CampaignContact

router = APIRouter(tags=["dashboard"])

# Campaign.id is a plain Postgres INTEGER (4-byte) primary key. Bounding
# campaign_id to that range up front makes an absurdly large value a 422
# (FastAPI validation) instead of an unhandled 500 -- psycopg raises
# NumericValueOutOfRange if a bigger Python int is ever bound into an
# int4 query parameter.
_CAMPAIGN_ID_QUERY = Query(default=None, ge=1, le=2_147_483_647)

# Task 6.2: split for the Plotly view. PRIMARY_STAGES is a genuine
# progression a contact moves through in order; EXCEPTION_STAGES are
# terminal side-branches a contact lands in INSTEAD of continuing (e.g.
# BOUNCED doesn't happen "after" REPLIED). Charting all 8 as one funnel
# would visually imply a monotonic decline that isn't real, so the funnel
# only covers PRIMARY_STAGES, with EXCEPTION_STAGES broken out as a
# separate bar chart alongside it. FUNNEL_ORDER (the JSON endpoint's fixed
# stage order) is derived from these two rather than kept as an
# independent third list, so there's exactly one place that has to be
# updated if a status is ever added, moved, or removed.
PRIMARY_STAGES = [
    AssignmentStatus.PENDING,
    AssignmentStatus.SENT,
    AssignmentStatus.OPENED,
    AssignmentStatus.CLICKED,
    AssignmentStatus.REPLIED,
]
EXCEPTION_STAGES = [
    AssignmentStatus.BOUNCED,
    AssignmentStatus.UNSUBSCRIBED,
    AssignmentStatus.EXCLUDED,
]
FUNNEL_ORDER = PRIMARY_STAGES + EXCEPTION_STAGES


class FunnelStage(BaseModel):
    status: AssignmentStatus
    count: int


def _funnel_counts(
    db: Session, campaign_id: int | None
) -> dict[AssignmentStatus, int]:
    """Shared aggregate query behind both GET /dashboard (JSON) and
    GET /dashboard/view (Plotly HTML) -- one query, two presentations.
    """
    if campaign_id is not None and db.get(Campaign, campaign_id) is None:
        raise HTTPException(404, f"Campaign {campaign_id} not found")

    query = select(CampaignContact.status, func.count()).group_by(
        CampaignContact.status
    )
    if campaign_id is not None:
        query = query.where(CampaignContact.campaign_id == campaign_id)
    return dict(db.execute(query).all())


@router.get("/dashboard", response_model=list[FunnelStage])
def get_dashboard(
    campaign_id: int | None = _CAMPAIGN_ID_QUERY, db: Session = Depends(get_db)
):
    """Funnel-style aggregate: count of campaign_contacts assignments
    currently at each status, in a fixed stage order. Optionally scoped to
    one campaign_id; global across all campaigns if omitted.
    """
    counts = _funnel_counts(db, campaign_id)
    return [
        FunnelStage(status=status, count=counts.get(status, 0))
        for status in FUNNEL_ORDER
    ]


@router.get("/dashboard/view", response_class=HTMLResponse)
def get_dashboard_view(
    campaign_id: int | None = _CAMPAIGN_ID_QUERY, db: Session = Depends(get_db)
):
    """Task 6.2: same aggregate as GET /dashboard, rendered as a Plotly
    chart instead of raw JSON -- a funnel for the real PENDING->...->REPLIED
    progression, plus a bar chart for the terminal exception stages.
    """
    counts = _funnel_counts(db, campaign_id)

    fig = make_subplots(
        rows=1,
        cols=2,
        column_widths=[0.65, 0.35],
        specs=[[{"type": "funnel"}, {}]],
        subplot_titles=("Engagement funnel", "Terminal outcomes"),
    )
    fig.add_trace(
        go.Funnel(
            y=[status.value for status in PRIMARY_STAGES],
            x=[counts.get(status, 0) for status in PRIMARY_STAGES],
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(
            x=[status.value for status in EXCEPTION_STAGES],
            y=[counts.get(status, 0) for status in EXCEPTION_STAGES],
        ),
        row=1,
        col=2,
    )
    title = "Campaign Funnel" + ("" if campaign_id is None else f" (Campaign {campaign_id})")
    fig.update_layout(title=title, showlegend=False)

    # include_plotlyjs=True embeds the ~4MB plotly.js library directly in
    # the page rather than pointing at a CDN -- this route works even in
    # an offline/egress-restricted deployment, and the extra page weight
    # is a non-issue for a low-traffic reporting view.
    return fig.to_html(full_html=True, include_plotlyjs=True)
