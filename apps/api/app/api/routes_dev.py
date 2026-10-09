"""DEV ONLY: read simulated emails. Mounted only when APP_ENV is local/test AND
DEV_MAILBOX_ENABLED=true; never available in staging or production."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import EmailOutbox
from app.services.accounts import InvalidEmailError, normalize_email

router = APIRouter(prefix="/dev", tags=["dev"])


class MailOut(BaseModel):
    id: uuid.UUID
    to_email: str
    template: str
    data: dict[str, Any]
    created_at: datetime


@router.get("/mailbox", response_model=list[MailOut])
def mailbox(email: str, db: Annotated[Session, Depends(get_db)]) -> list[MailOut]:
    try:
        address = normalize_email(email)
    except InvalidEmailError:
        return []
    rows = db.scalars(
        select(EmailOutbox)
        .where(EmailOutbox.to_email == address)
        .order_by(EmailOutbox.created_at.desc())
        .limit(20)
    ).all()
    return [
        MailOut(
            id=r.id, to_email=r.to_email, template=r.template, data=r.data, created_at=r.created_at
        )
        for r in rows
    ]
