import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

def _get_engine():
    url = os.environ["DATABASE_URL"]
    return create_engine(url)


# Lazily initialized — only created when first accessed
_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = _get_engine()
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autocommit=False)
    return _SessionLocal


def SessionLocal():
    return get_session_factory()()


def get_db():
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()
