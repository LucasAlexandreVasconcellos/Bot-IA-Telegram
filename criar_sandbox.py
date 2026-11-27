"""
Script compatível de criação do banco SQLite local (`sandbox_jarvis.db`).
Protegido com `if __name__ == "__main__":` para permitir importação segura em testes.
"""
from __future__ import annotations

from jarvis_bot.seed import popular_sqlite

if __name__ == "__main__":
    destino = popular_sqlite(incluir_casos_borda=False)
    print(f"Banco de dados '{destino.name}' atualizado e populado com sucesso!")
