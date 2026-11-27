"""
Entrypoint principal e fachada retrocompatível do Jarvis KPI Bot.
- Não executa `TeleBot()`, `OpenAI()` nem `polling()` durante `import kpi_bot`, permitindo
  importação limpa em suítes de testes e de LLM Evals.
- Consulta SQL via Cliente/Servidor MCP + `sql_guard` + `quality` (PostgreSQL ou SQLite).
- Renderiza gráficos validados na Sandbox isolada (`jarvis_bot.charts`).
"""
from __future__ import annotations

from typing import Any

from jarvis_bot.agent import AgenteJarvis, ResultadoTurno
from jarvis_bot.charts import criar_grafico_sandbox
from jarvis_bot.db import DESCRICAO_SEMANTICA_TABELAS as ESQUEMA_BANCO
from jarvis_bot.db import DatabaseRepository
from jarvis_bot.mcp_client import ClienteMCPBanco
from jarvis_bot.schemas import EstruturaGrafico, RespostaAgente, RoteamentoConsulta
from jarvis_bot.telegram_bot import criar_aplicacao_telegram, iniciar_bot

__all__ = [
    "ESQUEMA_BANCO",
    "AgenteJarvis",
    "EstruturaGrafico",
    "RespostaAgente",
    "ResultadoTurno",
    "RoteamentoConsulta",
    "criar_aplicacao_telegram",
    "criar_grafico_sandbox",
    "executar_query_sqlite",
    "iniciar_bot",
    "rodar_sql_isolado",
]


def rodar_sql_isolado(
    sql_limpo: str, caminho_banco: str | None = None
) -> tuple[list[dict[str, Any]], int, str | None]:
    """
    Função retrocompatível que consulta o repositório somente leitura aplicando `sql_guard` e `quality`.
    """
    repo = DatabaseRepository(caminho_sqlite=caminho_banco) if caminho_banco else DatabaseRepository()
    res = repo.executar_consulta_leitura(sql_limpo)
    if not res.get("sucesso"):
        return [], 0, str(res.get("erro") or "Consulta bloqueada ou falhou.")
    return list(res.get("dados", [])), int(res.get("isolados", 0)), None


def executar_query_sqlite(
    sql: str, usar_mcp: bool = False, caminho_banco: str | None = None
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Executa a consulta validada via MCP (ou repositório direto em testes locais) com fallback seguro
    de metadados (sem expor tracebacks nem vazar números de outros meses — DEF-006 / DEF-015).
    """
    if caminho_banco:
        repo = DatabaseRepository(caminho_sqlite=caminho_banco)
        res = repo.executar_consulta_leitura(sql)
    else:
        cliente = ClienteMCPBanco(use_mcp=usar_mcp)
        res = cliente.consultar_sql(sql)

    if not res.get("sucesso"):
        return None, str(res.get("erro") or "Não foi possível executar a consulta.")
    return res, None


if __name__ == "__main__":
    iniciar_bot()
