from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Integer, String, DateTime
from sqlalchemy.sql import quoted_name
from db import Base

class Relatorio(Base):
    __tablename__ = "relatorio"

    relatorio_number: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, nullable=False
    )

    # timestamps sem fuso (combina com "timestamp without time zone")
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

    # "user" é reservado → garantir citação
    user: Mapped[str | None] = mapped_column(quoted_name("user", True), String, nullable=True)

    def __repr__(self) -> str:
        return f"<Relatorio #{self.relatorio_number} user={self.user} nome={self.nome}>"
