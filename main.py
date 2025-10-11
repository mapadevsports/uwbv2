# main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from db import Base, engine
import models  # registra os models antes do create_all

# importe os routers das rotas soltas na raiz
from dados_crus import router as dados_crus_router
from processamento_crus import router as processamento_crus_router

app = FastAPI(
    title="UWB API v2",
    description="API para gerenciamento e processamento de dados UWB",
    version="0.0.1",
)

# CORS aberto para dev (restrinja depois)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# cria tabelas e testa conexão no start
@app.on_event("startup")
def on_startup():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    Base.metadata.create_all(bind=engine)

# ---- rotas principais ----
app.include_router(dados_crus_router)
app.include_router(processamento_crus_router)

@app.get("/health")
def health_check():
    return {"status": "ok", "version": "0.0.1"}

@app.get("/")
def root():
    return {"message": "Bem-vindo à UWB API v2 🎯"}
