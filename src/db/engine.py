import os

from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()

DB_PATH = os.environ.get("DB_PATH", "bottlebot.db")
engine = create_engine(f"sqlite:///{DB_PATH}")
