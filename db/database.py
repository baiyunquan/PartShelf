import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv
from starlette.requests import Request
from app.user_identity import SESSION_USERNAME_KEY, USERNAME_COOKIE_NAME, normalize_username

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

raw_db_url = os.getenv("DATABASE_URL", "sqlite:///./partshelf.db")
if raw_db_url.startswith("sqlite:///./"):
    rel_file = raw_db_url[len("sqlite:///./"):]
    SQLALCHEMY_DATABASE_URL = f"sqlite:///{(BASE_DIR / rel_file).resolve().as_posix()}"
elif raw_db_url == "sqlite:///partshelf.db":
    SQLALCHEMY_DATABASE_URL = f"sqlite:///{(BASE_DIR / 'partshelf.db').resolve().as_posix()}"
else:
    SQLALCHEMY_DATABASE_URL = raw_db_url

connect_args = {"check_same_thread": False} if SQLALCHEMY_DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args=connect_args, echo=True) 
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db(request: Request):
    db = SessionLocal()
    db.info[SESSION_USERNAME_KEY] = normalize_username(
        request.cookies.get(USERNAME_COOKIE_NAME)
    )
    try:
        yield db
    finally:
        db.close()
