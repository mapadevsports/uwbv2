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

    # campos extras que aparecem no seu print
    distancia_percorrida: Mapped[float | None] = mapped_column(Float)
    tempo_em_segundos: Mapped[int | None] = mapped_column(Integer)

    def __repr__(self) -> str:
        return f"<DistanciaProcessada id={self.id} tag={self.tag_number} x={self.x} y={self.y}>"
