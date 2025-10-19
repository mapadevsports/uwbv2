# models.py
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Integer, String, Float, DateTime, func
from sqlalchemy.sql import quoted_name
from db import Base


# --------------------- Leituras brutas --------------------- #
class DistanciaUWB(Base):
    __tablename__ = "distancias_uwb"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tag_number: Mapped[str] = mapped_column(String(50), nullable=False)

    da0: Mapped[float | None] = mapped_column(Float)
    da1: Mapped[float | None] = mapped_column(Float)
    da2: Mapped[float | None] = mapped_column(Float)
    da3: Mapped[float | None] = mapped_column(Float)
    da4: Mapped[float | None] = mapped_column(Float)
    da5: Mapped[float | None] = mapped_column(Float)
    da6: Mapped[float | None] = mapped_column(Float)
    da7: Mapped[float | None] = mapped_column(Float)

    kx: Mapped[float | None] = mapped_column(Float)
    ky: Mapped[float | None] = mapped_column(Float)

    criado_em: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<DistanciaUWB id={self.id} tag={self.tag_number}>"


# --------------------- Leituras processadas --------------------- #
class DistanciaProcessada(Base):
    __tablename__ = "distancias_processadas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tag_number: Mapped[str] = mapped_column(String(50), nullable=False)

    x: Mapped[float | None] = mapped_column(Float)
    y: Mapped[float | None] = mapped_column(Float)

    criado_em: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    distancia_percorrida: Mapped[float | None] = mapped_column(Float)
    tempo_em_segundos: Mapped[int | None] = mapped_column(Integer)

    def __repr__(self) -> str:
        return (
            f"<DistanciaProcessada id={self.id} tag={self.tag_number} "
            f"x={self.x} y={self.y}>"
        )


# --------------------- Relatórios --------------------- #
class Relatorio(Base):
    """
    Mapeamento da tabela 'relatorio' conforme estrutura atual:
      - relatorio_number (PK)
      - inicio_do_relatorio
      - fim_do_relatorio
      - kx, ky (varchar)
      - nome (varchar(100))
      - "user" (varchar)  ← nome reservado → quoted_name
    """
    __tablename__ = "relatorio"

    relatorio_number: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, nullable=False
    )

    # timestamps SEM fuso para casar com "timestamp without time zone"
    inicio_do_relatorio: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    fim_do_relatorio: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )

    # varchar no banco
    kx: Mapped[str | None] = mapped_column(String, nullable=True)
    ky: Mapped[str | None] = mapped_column(String, nullable=True)

    nome: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # "user" é palavra reservada → usar quoted_name para garantir aspas
    user: Mapped[str | None] = mapped_column(quoted_name("user", True), String, nullable=True)

    def __repr__(self) -> str:
        return f"<Relatorio #{self.relatorio_number} user={self.user} nome={self.nome}>"
