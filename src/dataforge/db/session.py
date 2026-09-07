from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def make_engine(database_url: str):
    return create_engine(database_url)


def make_session(database_url: str) -> Session:
    return sessionmaker(bind=make_engine(database_url))()
