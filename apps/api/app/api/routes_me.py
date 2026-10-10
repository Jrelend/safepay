"""Notifications and the simulated wallet (public API)."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.auth_context import CurrentUser
from app.db.session import get_db
from app.db.transactions import atomic
from app.models import Notification
from app.services import deals as svc

router = APIRouter(tags=["me"])
DbDep = Annotated[Session, Depends(get_db)]


class NotificationOut(BaseModel):
    id: uuid.UUID
    kind: str
    deal_id: uuid.UUID | None
    data: dict[str, Any]
    created_at: datetime
    read: bool


class NotificationsOut(BaseModel):
    unread: int
    items: list[NotificationOut]


class WalletEntryOut(BaseModel):
    kind: str
    direction: str
    amount_mnt: str
    deal_id: uuid.UUID | None
    created_at: datetime


class WalletOut(BaseModel):
    simulated: bool = True
    balance_mnt: str
    entries: list[WalletEntryOut]


@router.get("/me/notifications", response_model=NotificationsOut)
def notifications(ctx: CurrentUser, db: DbDep) -> NotificationsOut:
    rows = db.scalars(
        select(Notification)
        .where(Notification.user_id == ctx.user_id)
        .order_by(Notification.created_at.desc())
        .limit(100)
    ).all()
    return NotificationsOut(
        unread=svc.unread_count(db, user_id=ctx.user_id),
        items=[
            NotificationOut(
                id=n.id,
                kind=n.kind,
                deal_id=n.deal_id,
                data=n.data,
                created_at=n.created_at,
                read=n.read_at is not None,
            )
            for n in rows
        ],
    )


@router.post("/me/notifications/read-all", status_code=204)
def read_all(ctx: CurrentUser, db: DbDep) -> Response:
    with atomic(db):
        db.execute(
            update(Notification)
            .where(Notification.user_id == ctx.user_id, Notification.read_at.is_(None))
            .values(read_at=datetime.now().astimezone())
        )
    return Response(status_code=204)


@router.get("/me/wallet", response_model=WalletOut)
def wallet(ctx: CurrentUser, db: DbDep) -> WalletOut:
    balance, rows = svc.wallet(db, user_id=ctx.user_id)
    return WalletOut(
        balance_mnt=str(balance),
        entries=[
            WalletEntryOut(
                kind=tx.kind,
                direction=entry.direction.value,
                amount_mnt=str(entry.amount_mnt),
                deal_id=tx.deal_id,
                created_at=entry.created_at,
            )
            for entry, tx in rows
        ],
    )
