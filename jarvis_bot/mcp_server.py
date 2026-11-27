"""
Servidor MCP oficial do Jarvis KPI Bot (`FastMCP`).
Expõe ferramentas padronizadas de leitura sobre PostgreSQL / SQLite aplicando:
- Allowlist estrita de tabelas (`indicadores_empresa`, `vendas_lojas`)
- Validação sintática `sql_guard` (`sqlglot` + `LIMIT`)
- Decodificação defensiva (`text_factory = bytes`) e sanitização `quality.py`
- Retorno estruturado em JSON UTF-8 sem vazamento de tracebacks (DEF-010 / CT-029).
"""
from __future__ import annotations

import json
from typing import Any

from jarvis_bot.db import BancoIndisponivelErro, DatabaseRepository
from jarvis_bot.sql_guard import SQLValidacaoErro


def _obter_repo() -> DatabaseRepository:
    return DatabaseRepository()


def listar_tabelas(repo: DatabaseRepository | None = None) -> str:
    """Lista todas as tabelas corporativas autorizadas disponíveis no banco de dados."""
    repositorio = repo or _obter_repo()
    try:
        tabelas = repositorio.listar_tabelas()
        return json.dumps(
            {"sucesso": True, "tabelas": tabelas},
            ensure_ascii=False,
        )
    except BancoIndisponivelErro as exc:
        return json.dumps({"sucesso": False, "erro": str(exc)}, ensure_ascii=False)
    except Exception:
        return json.dumps(
            {"sucesso": False, "erro": "Não foi possível listar as tabelas no momento."},
            ensure_ascii=False,
        )


def obter_esquema_tabela(nome_tabela: str, repo: DatabaseRepository | None = None) -> str:
    """Retorna as colunas e tipos de dados de uma tabela corporativa autorizada."""
    repositorio = repo or _obter_repo()
    try:
        colunas = repositorio.obter_esquema_tabela(nome_tabela)
        if not colunas:
            return json.dumps(
                {"sucesso": False, "erro": f"A tabela '{nome_tabela}' não foi encontrada."},
                ensure_ascii=False,
            )
        return json.dumps(
            {"sucesso": True, "tabela": nome_tabela.strip().lower(), "colunas": colunas},
            ensure_ascii=False,
        )
    except (SQLValidacaoErro, BancoIndisponivelErro) as exc:
        return json.dumps({"sucesso": False, "erro": str(exc)}, ensure_ascii=False)
    except Exception:
        return json.dumps(
            {"sucesso": False, "erro": "Não foi possível obter o esquema solicitado."},
            ensure_ascii=False,
        )


def executar_consulta_sql(query: str, repo: DatabaseRepository | None = None) -> str:
    """Executa consultas SELECT de leitura com validação SQLGlot e sanitização de qualidade."""
    repositorio = repo or _obter_repo()
    resultado: dict[str, Any] = repositorio.executar_consulta_leitura(query)
    return json.dumps(resultado, ensure_ascii=False)


def criar_instancia_fastmcp() -> Any:
    """Cria e registra as ferramentas no servidor MCP (`MCPServer` v2 / `FastMCP` v1)."""
    try:
        from mcp.server.mcpserver import MCPServer as _ServidorMCPCls
    except ImportError:
        from mcp.server.fastmcp import FastMCP as _ServidorMCPCls

    mcp = _ServidorMCPCls("Servidor Banco Jarvis")

    @mcp.tool(name="listar_tabelas")
    def _tool_listar_tabelas() -> str:
        """Lista todas as tabelas corporativas autorizadas disponíveis no banco de dados."""
        return listar_tabelas()

    @mcp.tool(name="obter_esquema_tabela")
    def _tool_obter_esquema_tabela(nome_tabela: str) -> str:
        """Retorna as colunas e os tipos de dados de uma tabela corporativa específica."""
        return obter_esquema_tabela(nome_tabela)

    @mcp.tool(name="executar_consulta_sql")
    def _tool_executar_consulta_sql(query: str) -> str:
        """Executa apenas consultas SELECT seguras e higienizadas na base corporativa."""
        return executar_consulta_sql(query)

    return mcp


def iniciar_servidor_mcp() -> None:
    mcp = criar_instancia_fastmcp()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    iniciar_servidor_mcp()
