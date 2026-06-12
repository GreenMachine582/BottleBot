import os

from sqlalchemy import create_engine

DB_PATH = os.environ.get("DB_PATH", "bottlebot.db")
engine = create_engine(f"sqlite:///{DB_PATH}")
