from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import Engine

from app.core.config import Settings
from app.db.session import get_engine


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
EngineDep = Annotated[Engine, Depends(get_engine)]
