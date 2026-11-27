"""
Script compatível de população do PostgreSQL utilizando `DATABASE_ADMIN_URL` / `POSTGRES_URL` do `.env`.
Sem credenciais hardcoded no código-fonte.
"""
from __future__ import annotations

from jarvis_bot.seed import popular_postgresql


def popular_postgres(incluir_casos_borda: bool = True) -> None:
    print("Conectando ao PostgreSQL via configuração de ambiente...")
    popular_postgresql(incluir_casos_borda=incluir_casos_borda)
    print("PostgreSQL configurado e populado com sucesso!")


if __name__ == "__main__":
    popular_postgres(incluir_casos_borda=True)
