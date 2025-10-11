import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# Lê a URL do Render (Settings → Environment → DATABASE_URL)
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL não definida. Configure no Render (ou no .env local)."
    )

# Dica: se o Render exigir TLS/SSL e der erro de SSL, adicione '?sslmode=require' na URL.
# Ex.: postgresql://...render.com/uwb1?sslmode=require

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,   # evita conexões zumbis
    pool_size=5,          # bons defaults; ajuste se necessário
    max_overflow=10,
)

class Base(DeclarativeBase):
    pass

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
