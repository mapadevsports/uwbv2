from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Integer, String, Float, DateTime, func
from db import Base


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


# ===================== NOVO MODELO =====================

class Relatorio(Base):
    """
    Mapeamento da tabela 'relatorio' conforme o screenshot.
    Observação: a coluna primária aparece como 'relatorio_number' (sem 'r' no fim).
    Mantemos exatamente esse nome para evitar divergência com o schema atual.
    """
    __tablename__ = "relatorio"

    # Nome físico da coluna preservado via primeiro argumento do mapped_column
    relatorio_number: Mapped[int] = mapped_column(
        "relatorio_number", Integer, primary_key=True, autoincrement=True, nullable=False
    )

    inicio_do_relatorio: Mapped[DateTime | None] = mapped_column(
        "inicio_do_relator",  # corresponde a "timestamp without time zone"
        DateTime(timezone=False),
        nullable=True,
        server_default=None,
    )
    fim_do_relatorio: Mapped[DateTime | None] = mapped_column(
        "fim_do_relatorio",
        DateTime(timezone=False),
        nullable=True,
        server_default=None,
    )

    # Na UI estão como character varying; mantemos String (sem conversão)
    kx: Mapped[str | None] = mapped_column(String, nullable=True)
    ky: Mapped[str | None] = mapped_column(String, nullable=True)

    # 'nome' com limite 100 conforme a UI
    nome: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # 'user' (sem limite explícito na UI)
    user: Mapped[str | None] = mapped_column(String, nullable=True)

    def __repr__(self) -> str:
        return f"<Relatorio #{self.relatorio_number} user={self.user} nome={self.nome}>"
