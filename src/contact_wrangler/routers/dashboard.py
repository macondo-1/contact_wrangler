from fastapi import APIRouter, Depends, HTTPException
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


class FunnelStage(BaseModel):
    status: AssignmentStatus
    count: int


@router.get("/dashboard", response_model=list[FunnelStage])
def get_dashboard(campaign_id: int | None = None, db: Session = Depends(get_db)):
    """Funnel-style aggregate: count of campaign_contacts assignments
    currently at each status, in a fixed stage order. Optionally scoped to
    one campaign_id; global across all campaigns if omitted.
    """
    query = select(CampaignContact.status, func.count()).group_by(
        CampaignContact.status
    )
    if campaign_id is not None:
        if db.get(Campaign, campaign_id) is None:
            raise HTTPException(404, f"Campaign {campaign_id} not found")
        query = query.where(CampaignContact.campaign_id == campaign_id)

    counts = dict(db.execute(query).all())
    return [
        FunnelStage(status=status, count=counts.get(status, 0))
        for status in FUNNEL_ORDER
    ]
