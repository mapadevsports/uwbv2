import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

raw_url = os.getenv("DATABASE_URL")
if not raw_url:
    raise RuntimeError("DATABASE_URL não definida.")

# Força o driver psycopg3
if raw_url.startswith("postgresql://"):
    DATABASE_URL = "postgresql+psycopg://" + raw_url[len("postgresql://"):]
else:
    DATABASE_URL = raw_url

# Se precisar TLS no Render:
# if "sslmode=" not in DATABASE_URL:
#     sep = "&" if "?" in DATABASE_URL else "?"
#     DATABASE_URL = f"{DATABASE_URL}{sep}sslmode=require"

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=10)

class Base(DeclarativeBase): pass
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
