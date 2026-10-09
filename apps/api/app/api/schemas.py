"""Shared response models. Money is serialized as a decimal STRING so that
BIGINT-sized MNT amounts never lose precision in JavaScript."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.domain.deal_states import DealAction, DealStatus
from app.domain.deal_terms import DeliveryMethod, ItemType
from app.models import ParticipantRole


class DealSummaryOut(BaseModel):
    id: uuid.UUID
    reference: str
    title: str
    amount_mnt: str
    status: DealStatus
    my_role: ParticipantRole
    updated_at: datetime


class DealOut(BaseModel):
    id: uuid.UUID
    reference: str
    title: str
    description: str
    amount_mnt: str
    currency: str
    status: DealStatus
    version: int
    item_type: ItemType
    delivery_method: DeliveryMethod
    inspection_days: int
    my_role: ParticipantRole
    created_by_me: bool
    counterparty_name: str | None
    counterparty_phone: str | None
    my_accepted: bool
    counterparty_accepted: bool
    dispute_id: uuid.UUID | None
    actions: list[DealAction]
    auto_release_at: datetime | None
    status_changed_at: datetime
    created_at: datetime


class TimelineEventOut(BaseModel):
    action: str
    actor: str
    occurred_at: datetime
    data: dict[str, Any]


class PostingOut(BaseModel):
    kind: str
    amount_mnt: str
    created_at: datetime
