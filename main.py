from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

# 👇 importa direto da raiz
from db import Base, engine
import models  # garante que as classes sejam registradas no Base antes do create_all

app = FastAPI(
    title="UWB API v2",
    description="API para gerenciamento e processamento de dados UWB",
    version="0.0.1",
)

# 🌐 CORS (liberado no dev; restrinja em produção)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🔌 Testa conexão e cria tabelas no startup (enquanto não usa Alembic)
@app.on_event("startup")
def on_startup():
    # Teste rápido de conexão (útil no Render)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    # Cria tabelas dos models já importados (não sobrescreve existentes)
    Base.metadata.create_all(bind=engine)

# 🩺 Healthcheck
@app.get("/health")
def health_check():
    return {"status": "ok", "version": "0.0.1"}

# 👋 Rota raiz
@app.get("/")
def root():
    return {"message": "Bem-vindo à UWB API v2 🎯"}
