import plotly.graph_objects as go
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from plotly.subplots import make_subplots
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from contact_wrangler.db import get_db
from contact_wrangler.models import AssignmentStatus, Campaign, CampaignContact

router = APIRouter(tags=["dashboard"])

# Fixed order so the response is stable and chart-ready (Phase 6 Plotly funnel)
# even when some stages currently have zero assignments -- a chart backed by
# a varying set of stages (whatever happens to have data today) would jump
# around release to release, which is worse for a funnel visualization than
# always showing every stage, count 0 included.
FUNNEL_ORDER = [
    AssignmentStatus.PENDING,
    AssignmentStatus.SENT,
    AssignmentStatus.OPENED,
    AssignmentStatus.CLICKED,
    AssignmentStatus.REPLIED,
    AssignmentStatus.BOUNCED,
    AssignmentStatus.UNSUBSCRIBED,
    AssignmentStatus.EXCLUDED,
]

# Task 6.2: split for the Plotly view. PRIMARY_STAGES is a genuine
# progression a contact moves through in order; EXCEPTION_STAGES are
# terminal side-branches a contact lands in INSTEAD of continuing (e.g.
# BOUNCED doesn't happen "after" REPLIED). Charting all 8 as one funnel
# would visually imply a monotonic decline that isn't real, so the funnel
# only covers PRIMARY_STAGES, with EXCEPTION_STAGES broken out as a
# separate bar chart alongside it.
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
def get_dashboard(campaign_id: int | None = None, db: Session = Depends(get_db)):
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
def get_dashboard_view(campaign_id: int | None = None, db: Session = Depends(get_db)):
    """Task 6.2: same aggregate as GET /dashboard, rendered as a Plotly
    chart instead of raw JSON -- a funnel for the real PENDING->...->REPLIED
    progression, plus a bar chart for the terminal exception stages.
    """
    counts = _funnel_counts(db, campaign_id)

    fig = make_subplots(
        rows=1,
        cols=2,
        column_widths=[0.65, 0.35],
        specs=[[{"type": "funnel"}, {"type": "xy"}]],
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
    title = "Campaign Funnel" if campaign_id is None else f"Campaign {campaign_id} Funnel"
    fig.update_layout(title=title, showlegend=False)

    return fig.to_html(full_html=True, include_plotlyjs="cdn")
