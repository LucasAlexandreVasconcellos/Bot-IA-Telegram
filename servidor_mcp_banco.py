"""
Entrypoint retrocompatível do Servidor MCP (`jarvis_bot.mcp_server`).
"""
from __future__ import annotations

from jarvis_bot.mcp_server import (
    criar_instancia_fastmcp,
    executar_consulta_sql,
    iniciar_servidor_mcp,
    listar_tabelas,
    obter_esquema_tabela,
)

__all__ = [
    "criar_instancia_fastmcp",
    "executar_consulta_sql",
    "iniciar_servidor_mcp",
    "listar_tabelas",
    "obter_esquema_tabela",
]

if __name__ == "__main__":
    iniciar_servidor_mcp()
