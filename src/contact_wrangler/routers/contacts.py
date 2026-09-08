import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from contact_wrangler.db import get_db
from contact_wrangler.ingestion import import_contacts

router = APIRouter(prefix="/contacts", tags=["contacts"])


class ImportResult(BaseModel):
    inserted: int
    skipped_duplicate_count: int


@router.post("/import", response_model=ImportResult)
async def import_contacts_endpoint(request: Request, db: Session = Depends(get_db)):
    content_type = request.headers.get("content-type", "")

    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        file = form.get("file")
        if file is None:
            raise HTTPException(400, "Expected a 'file' field in the form data")
        raw = await file.read()
        text = raw.decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(text)))

    elif content_type.startswith("application/json"):
        body = await request.json()
        if not isinstance(body, list):
            raise HTTPException(400, "JSON body must be a list of contact objects")
        rows = body

    else:
        raise HTTPException(
            415, "Content-Type must be multipart/form-data (CSV) or application/json"
        )

    return import_contacts(db, rows)
