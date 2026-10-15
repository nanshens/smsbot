from functools import lru_cache
from sqlalchemy import create_engine, text
from .config import settings


@lru_cache
def engine():
    return create_engine(settings().database, pool_pre_ping=True, pool_size=5, max_overflow=5,
                         connect_args={'connect_timeout': 10}, hide_parameters=True)


def one(db, sql, **params):
    return db.execute(text(sql), params).mappings().first()


def rows(db, sql, **params):
    return list(db.execute(text(sql), params).mappings())


def run(db, sql, **params):
    return db.execute(text(sql), params)


def connection():
    with engine().begin() as db:
        yield db
