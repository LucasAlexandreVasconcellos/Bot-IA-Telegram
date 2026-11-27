"""
Camada de Repositório Híbrido (PostgreSQL Read-Only + SQLite Read-Only) do Jarvis KPI Bot.
Unifica acesso somente leitura, `sql_guard`, `quality` e fallback seguro de metadados (sem expor tracebacks).
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any

from jarvis_bot.config import ConfiguracaoJarvis, obter_config, resolver_caminho_sqlite
from jarvis_bot.quality import LIMITE_LINHAS_CONTEXTO_IA, sanitizar_linhas_consulta_detalhada
from jarvis_bot.sql_guard import TABELAS_PERMITIDAS, SQLValidacaoErro, validar_e_preparar_sql

logger = logging.getLogger("jarvis.db")

DESCRICAO_SEMANTICA_TABELAS = """
1. indicadores_empresa:
   - id (INTEGER): identificador único
   - departamento (TEXT): ex. 'Financeiro', 'Marketing', 'Operações'
   - metrica (TEXT): ex. 'Faturamento Líquido', 'EBITDA', 'Lucro Líquido', 'Custo de Aquisição (CAC)', 'Taxa de Churn (Cancelamentos)', 'Retorno sobre Investimento (ROI)'
   - tipo_periodo (TEXT): 'Anual', 'Mensal', 'Semanal'
   - periodo (TEXT): ex. '2025', 'Julho/2026', 'Agosto/2026', 'Semana 1 - Ago/2026' .. 'Semana 4 - Ago/2026'
   - valor_monetario (REAL): valor expresso em milhões de reais (R$ milhões) para indicadores financeiros, ou índice/taxa conforme a métrica
   - variacao (REAL): variação percentual (%) no período (pode ser positiva ou negativa)

2. vendas_lojas:
   - id (INTEGER): identificador único
   - loja (TEXT): ex. 'Loja Centro', 'Loja Shopping Sul', 'Loja Norte', 'Loja Oeste'
   - linha_produto (TEXT): ex. 'Casual', 'Esportivo', 'Formal'
   - ano (INTEGER): ex. 2026
   - mes (TEXT): ex. 'Janeiro/2026', 'Fevereiro/2026'
   - valor_venda (REAL): valor da venda em reais (R$)
""".strip()


class BancoIndisponivelErro(RuntimeError):
    """Exceção controlada para indisponibilidade ou ausência do banco de dados."""


class DatabaseRepository:
    """Repositório somente leitura compatível com SQLite (`mode=ro`) e PostgreSQL (`readonly=True`)."""

    def __init__(
        self,
        database_url: str | None = None,
        caminho_sqlite: Path | None = None,
        timeout_segundos: float = 10.0,
    ) -> None:
        cfg: ConfiguracaoJarvis = obter_config()
        if caminho_sqlite is not None:
            self.caminho_sqlite = Path(caminho_sqlite).resolve()
            self.database_url = f"sqlite:///{self.caminho_sqlite.as_posix()}"
            self.eh_postgres = False
        elif database_url is not None:
            self.database_url = database_url.strip()
            self.eh_postgres = self.database_url.startswith(("postgres://", "postgresql://"))
            self.caminho_sqlite = resolver_caminho_sqlite(self.database_url, cfg.caminho_sqlite)
        else:
            self.database_url = cfg.database_url
            self.eh_postgres = cfg.eh_postgres
            self.caminho_sqlite = cfg.caminho_sqlite
        self.timeout_segundos = timeout_segundos

    def _abrir_conexao_sqlite_ro(self) -> sqlite3.Connection:
        if not self.caminho_sqlite.exists() or not self.caminho_sqlite.is_file():
            logger.error("Arquivo SQLite não encontrado em: %s", self.caminho_sqlite)
            raise BancoIndisponivelErro(
                "A base de dados corporativa está indisponível no momento."
            )
        uri = f"file:{self.caminho_sqlite.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=self.timeout_segundos, check_same_thread=False)
        conn.text_factory = bytes
        return conn

    def _abrir_conexao_postgres_ro(self) -> Any:
        try:
            import psycopg2
        except ImportError as exc:
            logger.error("Driver psycopg2 não instalado para conexão PostgreSQL.")
            raise BancoIndisponivelErro(
                "O conector do banco PostgreSQL não está disponível no servidor."
            ) from exc

        try:
            conn = psycopg2.connect(
                self.database_url,
                connect_timeout=max(1, int(self.timeout_segundos)),
                options=f"-c statement_timeout={int(self.timeout_segundos * 1000)}",
            )
            conn.set_session(readonly=True, autocommit=True)
            return conn
        except Exception as exc:
            logger.error("Falha ao conectar no PostgreSQL: %s", exc)
            raise BancoIndisponivelErro(
                "Não foi possível estabelecer conexão com o banco de dados corporativo."
            ) from exc

    def _executar_raw_ro(self, sql_preparado: str) -> list[dict[str, Any]]:
        """Executa um `SELECT` já validado em conexão read-only com timeout efetivo."""
        if self.eh_postgres:
            conn = self._abrir_conexao_postgres_ro()
            try:
                with conn.cursor() as cur:
                    cur.execute(sql_preparado)
                    if not cur.description:
                        return []
                    colunas = [desc[0] for desc in cur.description]
                    return [dict(zip(colunas, row)) for row in cur.fetchall()]
            finally:
                conn.close()

        conn = self._abrir_conexao_sqlite_ro()
        timer = threading.Timer(self.timeout_segundos, conn.interrupt)
        timer.daemon = True
        timer.start()
        try:
            cur = conn.cursor()
            cur.execute(sql_preparado)
            if not cur.description:
                return []
            colunas = [
                desc[0].decode("utf-8", errors="replace")
                if isinstance(desc[0], (bytes, bytearray))
                else str(desc[0])
                for desc in cur.description
            ]
            return [dict(zip(colunas, row)) for row in cur.fetchall()]
        except sqlite3.OperationalError as exc:
            if "interrupted" in str(exc).lower():
                logger.warning("Consulta SQLite interrompida por timeout (%.1fs).", self.timeout_segundos)
                raise BancoIndisponivelErro(
                    "A consulta excedeu o tempo máximo permitido e foi interrompida."
                ) from exc
            raise
        finally:
            timer.cancel()
            conn.close()

    def listar_tabelas(self) -> list[str]:
        """Lista apenas as tabelas autorizadas existentes no banco."""
        if self.eh_postgres:
            conn = self._abrir_conexao_postgres_ro()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public' ORDER BY table_name;"
                    )
                    nomes = [r[0] for r in cur.fetchall()]
            finally:
                conn.close()
        else:
            conn = self._abrir_conexao_sqlite_ro()
            try:
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
                nomes = [
                    r[0].decode("utf-8", errors="replace")
                    if isinstance(r[0], (bytes, bytearray))
                    else str(r[0])
                    for r in cur.fetchall()
                ]
            finally:
                conn.close()

        return [n for n in nomes if n.lower() in TABELAS_PERMITIDAS]

    def obter_esquema_tabela(self, nome_tabela: str) -> list[dict[str, str]]:
        """Retorna colunas e tipos apenas se `nome_tabela` pertencer à allowlist."""
        limpo = (nome_tabela or "").strip().lower()
        if limpo not in TABELAS_PERMITIDAS:
            raise SQLValidacaoErro(
                f"A tabela '{nome_tabela}' não é autorizada ou não existe. "
                f"Tabelas permitidas: {', '.join(sorted(TABELAS_PERMITIDAS))}."
            )

        if self.eh_postgres:
            conn = self._abrir_conexao_postgres_ro()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT column_name, data_type FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = %s "
                        "ORDER BY ordinal_position;",
                        (limpo,),
                    )
                    return [{"coluna": r[0], "tipo": r[1].upper()} for r in cur.fetchall()]
            finally:
                conn.close()

        conn = self._abrir_conexao_sqlite_ro()
        try:
            cur = conn.cursor()
            # Seguro pois `limpo` pertence estritamente a TABELAS_PERMITIDAS
            cur.execute(f"PRAGMA table_info({limpo});")
            esquema: list[dict[str, str]] = []
            for row in cur.fetchall():
                col_nome = (
                    row[1].decode("utf-8", errors="replace")
                    if isinstance(row[1], (bytes, bytearray))
                    else str(row[1])
                )
                col_tipo = (
                    row[2].decode("utf-8", errors="replace")
                    if isinstance(row[2], (bytes, bytearray))
                    else str(row[2])
                )
                esquema.append({"coluna": col_nome, "tipo": col_tipo})
            return esquema
        finally:
            conn.close()

    def obter_metadados_disponiveis(self) -> dict[str, list[str]]:
        """
        Retorna apenas os filtros válidos disponíveis no banco (SEM valores monetários),
        prevenindo a Armadilha do Fallback (DEF-015) em consultas vazias.
        """
        meta: dict[str, list[str]] = {
            "departamentos_disponiveis": [],
            "metricas_disponiveis": [],
            "periodos_indicadores_disponiveis": [],
            "lojas_disponiveis": [],
            "linhas_produto_disponiveis": [],
            "meses_vendas_disponiveis": [],
        }
        try:
            ind_rows = self._executar_raw_ro(
                "SELECT DISTINCT departamento, metrica, periodo FROM indicadores_empresa LIMIT 200"
            )
            ind_san = sanitizar_linhas_consulta_detalhada(ind_rows).linhas_limpas
            meta["departamentos_disponiveis"] = sorted({r["departamento"] for r in ind_san if r.get("departamento")})
            meta["metricas_disponiveis"] = sorted({r["metrica"] for r in ind_san if r.get("metrica")})
            meta["periodos_indicadores_disponiveis"] = sorted({r["periodo"] for r in ind_san if r.get("periodo")})

            vnd_rows = self._executar_raw_ro(
                "SELECT DISTINCT loja, linha_produto, mes FROM vendas_lojas LIMIT 200"
            )
            vnd_san = sanitizar_linhas_consulta_detalhada(vnd_rows).linhas_limpas
            meta["lojas_disponiveis"] = sorted({r["loja"] for r in vnd_san if r.get("loja")})
            meta["linhas_produto_disponiveis"] = sorted({r["linha_produto"] for r in vnd_san if r.get("linha_produto")})
            meta["meses_vendas_disponiveis"] = sorted({r["mes"] for r in vnd_san if r.get("mes")})
        except Exception as exc:
            logger.warning("Não foi possível carregar metadados de fallback: %s", exc)
        return meta

    def executar_consulta_leitura(
        self,
        sql: str,
        limite_maximo: int = LIMITE_LINHAS_CONTEXTO_IA,
    ) -> dict[str, Any]:
        """
        Valida SQL (`sql_guard`), executa em conexão somente leitura, sanitiza registros
        por coluna (`quality`) e aplica fallback seguro de metadados quando vazio.
        """
        try:
            validado = validar_e_preparar_sql(
                sql=sql,
                eh_postgres=self.eh_postgres,
                limite_maximo=limite_maximo,
                permitir_select_constante=False,
            )
            logger.info("Executando SQL validado: %s", validado.sql_com_limite)
            brutos = self._executar_raw_ro(validado.sql_com_limite)
        except SQLValidacaoErro as val_err:
            logger.warning("Consulta SQL bloqueada pela validação: %s | SQL=%r", val_err, sql)
            return {
                "sucesso": False,
                "status": "bloqueado_validacao",
                "dados": [],
                "isolados": 0,
                "truncado": False,
                "erro": str(val_err),
            }
        except BancoIndisponivelErro as db_err:
            return {
                "sucesso": False,
                "status": "erro_indisponibilidade",
                "dados": [],
                "isolados": 0,
                "truncado": False,
                "erro": str(db_err),
            }
        except Exception as exc:
            logger.error("Erro operacional ao executar SQL %r: %s", sql, exc)
            return {
                "sucesso": False,
                "status": "erro_execucao",
                "dados": [],
                "isolados": 0,
                "truncado": False,
                "erro": "Não foi possível processar a consulta solicitada na base de dados.",
            }

        truncado_sql = len(brutos) > validado.limite_efetivo
        if truncado_sql:
            brutos = brutos[: validado.limite_efetivo]

        san = sanitizar_linhas_consulta_detalhada(brutos, limite=validado.limite_efetivo)
        truncado_final = truncado_sql or san.truncado

        # Caso especial CT-037: havia linhas no banco para o filtro, mas TODAS foram isoladas por qualidade
        if not san.linhas_limpas and len(brutos) > 0:
            return {
                "sucesso": True,
                "status": "isolado_qualidade",
                "aviso": (
                    f"Foram localizados {len(brutos)} registro(s) para o filtro consultado, "
                    "porém todos apresentaram inconsistências de qualidade e foram isolados preventivamente. "
                    "Informe ao usuário que os registros existentes para esse recorte estão em quarentena de qualidade."
                ),
                "dados": [],
                "isolados": san.isolados,
                "truncado": False,
            }

        # Caso CT-011 / DEF-015: consulta não retornou nenhuma linha — envia APENAS metadados sem valores!
        if not san.linhas_limpas:
            filtros = self.obter_metadados_disponiveis()
            return {
                "sucesso": True,
                "status": "vazio",
                "aviso": (
                    "A busca exata não retornou linhas para o filtro solicitado. "
                    "NÃO invente, NÃO estime e NÃO extrapole valores corporativos. "
                    "Informe claramente a ausência de dados para o filtro pedido e, se útil, "
                    "cite os períodos/departamentos disponíveis listados em 'filtros_disponiveis'."
                ),
                "dados": [],
                "filtros_disponiveis": filtros,
                "isolados": 0,
                "truncado": False,
            }

        resposta: dict[str, Any] = {
            "sucesso": True,
            "status": "ok",
            "dados": san.linhas_limpas,
            "isolados": san.isolados,
            "truncado": truncado_final,
        }
        if truncado_final:
            resposta["aviso_truncamento"] = (
                f"Resultado limitado aos primeiros {len(san.linhas_limpas)} registros válidos."
            )
        return resposta
