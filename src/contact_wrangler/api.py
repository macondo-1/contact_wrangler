from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from contact_wrangler.db import get_db
from contact_wrangler.routers import campaigns, contacts, dashboard, events

app = FastAPI()

app.include_router(contacts.router)
app.include_router(campaigns.router)
app.include_router(events.router)
app.include_router(dashboard.router)


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}