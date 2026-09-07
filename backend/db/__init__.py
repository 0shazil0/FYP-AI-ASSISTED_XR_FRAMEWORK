# backend/db/__init__.py
from .database import init_db, get_db, fetchall, fetchone, execute

__all__ = ["init_db", "get_db", "fetchall", "fetchone", "execute"]
