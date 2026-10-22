"""LOCAL DEMO ONLY: one-click account switching for presentations. Mounted only
when LOCAL_DEMO=true and APP_ENV is local/test; never in staging or production.

The seeded accounts and their passwords are public by design (see
``app/local_demo.py``). Sign-in itself still goes through the normal endpoints:
``/auth/login`` for the buyer and seller, and the admin API's password + TOTP
login for the admin, for which this returns the current one-time code.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app import local_demo
from app.core import totp

router = APIRouter(prefix="/demo", tags=["demo"])


class DemoAccountOut(BaseModel):
    key: Literal["buyer", "seller", "admin"]
    email: str
    display_name: str
    password: str


class DemoAdminCodeOut(BaseModel):
    code: str


@router.get("/accounts", response_model=list[DemoAccountOut])
def accounts() -> list[DemoAccountOut]:
    return [
        DemoAccountOut(
            key=p.key,
            email=p.email,
            display_name=p.display_name,
            password=local_demo.DEMO_ADMIN_PASSWORD
            if p.key == "admin"
            else local_demo.DEMO_PASSWORD,
        )
        for p in local_demo.PERSONAS
    ]


@router.get("/admin-code", response_model=DemoAdminCodeOut)
def admin_code(ahead: Annotated[int, Query(ge=0, le=1)] = 0) -> DemoAdminCodeOut:
    """The demo admin's code for the current 30 s step, or (``ahead=1``) the next one,
    which the login also accepts (±1 step drift) when the current one was just used."""
    step = totp.current_step() + ahead
    return DemoAdminCodeOut(code=totp.code_at(local_demo.DEMO_ADMIN_TOTP_SECRET, step))
