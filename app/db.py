import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from .config import settings

Path(settings.log_dir).mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO, handlers=[RotatingFileHandler(Path(settings.log_dir)/'sepsis_poc9.log', maxBytes=2_000_000, backupCount=2, encoding='utf-8'), logging.StreamHandler()], format='%(asctime)s %(levelname)s %(name)s %(message)s')
engine = create_engine(settings.database_url, connect_args={'check_same_thread': False, 'timeout': 10})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
class Base(DeclarativeBase): pass

@event.listens_for(engine, 'connect')
def sqlite_setup(dbapi, _):
    cur = dbapi.cursor()
    cur.execute('PRAGMA foreign_keys=ON')
    cur.execute('PRAGMA journal_mode=WAL')
    cur.execute('PRAGMA busy_timeout=10000')
    cur.close()

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()
