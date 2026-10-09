from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine

from app.core.config import Settings, get_settings
from app.db.session import get_engine

SettingsDep = Annotated[Settings, Depends(get_settings)]
EngineDep = Annotated[Engine, Depends(get_engine)]
