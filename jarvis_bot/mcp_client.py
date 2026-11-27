"""
Cliente MCP integrado ao Jarvis KPI Bot (`Telegram -> Agente -> Cliente MCP -> Servidor MCP -> Banco`).
Suporta:
1. Transporte oficial MCP `stdio` (subprocesso isolado sem repassar `OPENAI_API_KEY` ou `TELEGRAM_TOKEN`).
2. Fallback transparente em processo (`DatabaseRepository` / `mcp_server`) caso `use_mcp=False` ou o SDK `mcp`
   não esteja instalado em ambientes restritos de teste offline.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any

from jarvis_bot.config import RAIZ_PROJETO, obter_config
from jarvis_bot.db import DatabaseRepository
from jarvis_bot import mcp_server

logger = logging.getLogger("jarvis.mcp_client")

_CHAVES_SENSIVEIS_EXCLUIDAS = frozenset({"OPENAI_API_KEY", "TELEGRAM_TOKEN"})


def _construir_env_mcp_seguro(database_url: str) -> dict[str, str]:
    """Monta ambiente mínimo para o subprocesso MCP sem vazar tokens de IA/Telegram."""
    env_limpo = {
        k: v
        for k, v in os.environ.items()
        if k not in _CHAVES_SENSIVEIS_EXCLUIDAS
    }
    env_limpo["DATABASE_URL"] = database_url
    env_limpo["PYTHONUTF8"] = "1"
    return env_limpo


class ClienteMCPBanco:
    """Gateway de dados do Agente Jarvis via Model Context Protocol (MCP)."""

    def __init__(
        self,
        use_mcp: bool | None = None,
        database_url: str | None = None,
        repositorio_direto: DatabaseRepository | None = None,
    ) -> None:
        cfg = obter_config()
        self.use_mcp = cfg.use_mcp if use_mcp is None else use_mcp
        self.database_url = database_url or cfg.database_url
        self._repo_fallback = repositorio_direto or DatabaseRepository(database_url=self.database_url)

    def _mcp_sdk_disponivel(self) -> bool:
        try:
            import mcp  # noqa: F401

            return True
        except ImportError:
            return False

    async def _chamar_tool_stdio_async(self, nome_tool: str, argumentos: dict[str, Any]) -> str:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        servidor_script = str(RAIZ_PROJETO / "servidor_mcp_banco.py")
        parametros = StdioServerParameters(
            command=sys.executable,
            args=[servidor_script],
            env=_construir_env_mcp_seguro(self.database_url),
        )
        async with stdio_client(parametros) as (leitura, escrita):
            async with ClientSession(leitura, escrita) as sessao:
                await sessao.initialize()
                resposta = await sessao.call_tool(nome_tool, arguments=argumentos)
                if not resposta.content:
                    return "{}"
                return resposta.content[0].text

    def chamar_tool(self, nome_tool: str, argumentos: dict[str, Any] | None = None) -> dict[str, Any]:
        """Aciona uma ferramenta MCP (`stdio` quando ativo/disponível, ou em processo como fallback)."""
        args = argumentos or {}
        if self.use_mcp and self._mcp_sdk_disponivel():
            try:
                bruto = asyncio.run(self._chamar_tool_stdio_async(nome_tool, args))
                return json.loads(bruto)
            except Exception as exc:
                logger.error("Erro na comunicação STDIO com Servidor MCP (%s): %s", nome_tool, exc)
                return {
                    "sucesso": False,
                    "status": "erro_mcp",
                    "dados": [],
                    "isolados": 0,
                    "truncado": False,
                    "erro": "Falha de comunicação com o servidor de dados MCP.",
                }

        # Execução direta nas mesmas funções de ferramenta do MCP (em processo)
        if nome_tool == "listar_tabelas":
            return json.loads(mcp_server.listar_tabelas(repo=self._repo_fallback))
        if nome_tool == "obter_esquema_tabela":
            return json.loads(
                mcp_server.obter_esquema_tabela(
                    args.get("nome_tabela", ""), repo=self._repo_fallback
                )
            )
        if nome_tool == "executar_consulta_sql":
            return json.loads(
                mcp_server.executar_consulta_sql(
                    args.get("query", ""), repo=self._repo_fallback
                )
            )
        raise ValueError(f"Ferramenta MCP desconhecida: {nome_tool}")

    def consultar_sql(self, sql: str) -> dict[str, Any]:
        return self.chamar_tool("executar_consulta_sql", {"query": sql})

    def listar_tabelas(self) -> dict[str, Any]:
        return self.chamar_tool("listar_tabelas", {})

    def obter_esquema_tabela(self, nome_tabela: str) -> dict[str, Any]:
        return self.chamar_tool("obter_esquema_tabela", {"nome_tabela": nome_tabela})
