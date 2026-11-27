"""
Utilitário unificado de criação e população do esquema canônico (`indicadores_empresa` e `vendas_lojas`)
para SQLite e PostgreSQL, com suporte a modo limpo (`clean`) e modo de teste de borda (`dirty`).
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

from jarvis_bot.config import RAIZ_PROJETO, carregar_env_arquivo

DADOS_INDICADORES_REFERENCIA: list[tuple[str, str, str, str, float, float]] = [
    ("Financeiro", "Faturamento Líquido", "Anual", "2025", 145.2, 12.4),
    ("Financeiro", "EBITDA", "Anual", "2025", 42.1, 8.5),
    ("Marketing", "Custo de Aquisição (CAC)", "Anual", "2025", 0.005, -2.1),
    ("Financeiro", "Faturamento Líquido", "Mensal", "Julho/2026", 11.3, 2.1),
    ("Financeiro", "Lucro Líquido", "Mensal", "Julho/2026", 4.1, 1.5),
    ("Operações", "Taxa de Churn (Cancelamentos)", "Mensal", "Julho/2026", 0.012, -0.2),
    ("Financeiro", "Faturamento Líquido", "Mensal", "Agosto/2026", 12.4, 9.7),
    ("Financeiro", "Lucro Líquido", "Mensal", "Agosto/2026", 5.2, 26.8),
    ("Operações", "Taxa de Churn (Cancelamentos)", "Mensal", "Agosto/2026", 0.015, 0.3),
    ("Marketing", "Retorno sobre Investimento (ROI)", "Mensal", "Agosto/2026", 3.2, 15.0),
    ("Financeiro", "Faturamento Líquido", "Semanal", "Semana 1 - Ago/2026", 2.8, 1.1),
    ("Financeiro", "Faturamento Líquido", "Semanal", "Semana 2 - Ago/2026", 3.1, 10.7),
    ("Financeiro", "Faturamento Líquido", "Semanal", "Semana 3 - Ago/2026", 3.5, 12.9),
    ("Financeiro", "Faturamento Líquido", "Semanal", "Semana 4 - Ago/2026", 3.0, -14.2),
]

DADOS_VENDAS_REFERENCIA: list[tuple[str, str, int, str, float]] = [
    ("Loja Centro", "Casual", 2026, "Janeiro/2026", 120000.0),
    ("Loja Shopping Sul", "Casual", 2026, "Janeiro/2026", 185000.0),
    ("Loja Norte", "Casual", 2026, "Janeiro/2026", 140000.0),
    ("Loja Oeste", "Casual", 2026, "Janeiro/2026", 95000.0),
    ("Loja Centro", "Casual", 2026, "Fevereiro/2026", 130000.0),
    ("Loja Shopping Sul", "Casual", 2026, "Fevereiro/2026", 190000.0),
    ("Loja Norte", "Casual", 2026, "Fevereiro/2026", 155000.0),
    ("Loja Oeste", "Casual", 2026, "Fevereiro/2026", 105000.0),
    ("Loja Centro", "Esportivo", 2026, "Janeiro/2026", 85000.0),
    ("Loja Shopping Sul", "Esportivo", 2026, "Janeiro/2026", 110000.0),
    ("Loja Centro", "Formal", 2026, "Janeiro/2026", 90000.0),
    ("Loja Shopping Sul", "Formal", 2026, "Janeiro/2026", 125000.0),
]

DADOS_VENDAS_CASOS_BORDA: list[tuple[str, str, int, str, float]] = [
    ("Loja PromoÃ§Ã£o_Quebrada", "Casual", 2026, "Janeiro/2026", 45000.0),
    ("Loja Sudoeste â€• Filial", "Casual", 2026, "Fevereiro/2026", 78000.0),
    ("Loja Centro", "ColeÃ§Ã£o_Inverno", 2026, "Janeiro/2026", 62000.0),
    ("Loja Devolucoes_Gerais", "Casual", 2026, "Janeiro/2026", -32000.0),
    ("Loja Centro", "Casual", 2026, "Fevereiro/2026", -5000.0),
    ("Loja Reforma Fechada", "Casual", 2026, "Janeiro/2026", 0.0),
    ("Loja Centro", "Casual", 2026, "2026-04-XX_DATA_CORROMPIDA", 55000.0),
]


def popular_sqlite(
    caminho_banco: Path | str | None = None,
    incluir_casos_borda: bool = False,
) -> Path:
    """Cria e popula o banco SQLite local com o esquema canônico."""
    destino = Path(caminho_banco) if caminho_banco else (RAIZ_PROJETO / "sandbox_jarvis.db")
    if not destino.is_absolute():
        destino = (RAIZ_PROJETO / destino).resolve()
    destino.parent.mkdir(parents=True, exist_ok=True)

    conexao = sqlite3.connect(str(destino))
    try:
        cursor = conexao.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS indicadores_empresa (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                departamento TEXT,
                metrica TEXT,
                tipo_periodo TEXT,
                periodo TEXT,
                valor_monetario REAL,
                variacao REAL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS vendas_lojas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                loja TEXT,
                linha_produto TEXT,
                ano INTEGER,
                mes TEXT,
                valor_venda REAL
            )
            """
        )
        cursor.execute("DELETE FROM indicadores_empresa")
        cursor.execute("DELETE FROM vendas_lojas")

        cursor.executemany(
            """
            INSERT INTO indicadores_empresa (
                departamento, metrica, tipo_periodo, periodo, valor_monetario, variacao
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            DADOS_INDICADORES_REFERENCIA,
        )

        vendas = list(DADOS_VENDAS_REFERENCIA)
        if incluir_casos_borda:
            vendas.extend(DADOS_VENDAS_CASOS_BORDA)

        cursor.executemany(
            """
            INSERT INTO vendas_lojas (
                loja, linha_produto, ano, mes, valor_venda
            ) VALUES (?, ?, ?, ?, ?)
            """,
            vendas,
        )
        conexao.commit()
    finally:
        conexao.close()

    return destino


def popular_postgresql(
    database_url: str | None = None,
    incluir_casos_borda: bool = False,
) -> None:
    """Cria e popula as tabelas canônicas no PostgreSQL sem credenciais hardcoded."""
    carregar_env_arquivo()
    url = (
        database_url
        or os.getenv("DATABASE_ADMIN_URL")
        or os.getenv("POSTGRES_URL")
        or os.getenv("DATABASE_URL")
        or ""
    ).strip()
    if not url or not url.startswith(("postgres://", "postgresql://")):
        raise RuntimeError(
            "Defina DATABASE_ADMIN_URL (ou DATABASE_URL postgresql://...) no arquivo `.env` "
            "para popular o PostgreSQL."
        )

    import psycopg2

    conn = psycopg2.connect(url)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                DROP TABLE IF EXISTS vendas_lojas;
                DROP TABLE IF EXISTS indicadores_empresa;

                CREATE TABLE indicadores_empresa (
                    id SERIAL PRIMARY KEY,
                    departamento VARCHAR(100) NOT NULL,
                    metrica VARCHAR(150) NOT NULL,
                    tipo_periodo VARCHAR(50) NOT NULL,
                    periodo VARCHAR(100) NOT NULL,
                    valor_monetario NUMERIC(15, 4) NOT NULL,
                    variacao NUMERIC(8, 2) NOT NULL
                );

                CREATE TABLE vendas_lojas (
                    id SERIAL PRIMARY KEY,
                    loja VARCHAR(150) NOT NULL,
                    linha_produto VARCHAR(100) NOT NULL,
                    ano INT NOT NULL,
                    mes VARCHAR(100) NOT NULL,
                    valor_venda NUMERIC(15, 2) NOT NULL
                );
                """
            )

            cursor.executemany(
                """
                INSERT INTO indicadores_empresa (
                    departamento, metrica, tipo_periodo, periodo, valor_monetario, variacao
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                DADOS_INDICADORES_REFERENCIA,
            )

            vendas = list(DADOS_VENDAS_REFERENCIA)
            if incluir_casos_borda:
                vendas.extend(DADOS_VENDAS_CASOS_BORDA)

            cursor.executemany(
                """
                INSERT INTO vendas_lojas (
                    loja, linha_produto, ano, mes, valor_venda
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                vendas,
            )

            # Se o role somente leitura existir, garante permissão SELECT nas tabelas recriadas
            ro_user = (os.getenv("POSTGRES_READONLY_USER") or "jarvis_readonly").strip()
            if ro_user.isidentifier():
                cursor.execute(
                    f"""
                    DO $$
                    BEGIN
                        IF EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{ro_user}') THEN
                            EXECUTE 'GRANT SELECT ON TABLE indicadores_empresa, vendas_lojas TO {ro_user}';
                        END IF;
                    END
                    $$;
                    """
                )
        conn.commit()
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Popula o banco de dados do Jarvis KPI Bot.")
    parser.add_argument(
        "--target",
        choices=("sqlite", "postgres"),
        default="sqlite",
        help="Banco de destino a ser populado (padrão: sqlite).",
    )
    parser.add_argument(
        "--mode",
        choices=("clean", "dirty"),
        default="clean",
        help="'clean' grava apenas os dados de referência; 'dirty' adiciona casos de borda.",
    )
    parser.add_argument(
        "--sqlite-path",
        default=None,
        help="Caminho opcional do arquivo SQLite.",
    )
    args = parser.parse_args()
    sujo = args.mode == "dirty"

    if args.target == "postgres":
        popular_postgresql(incluir_casos_borda=sujo)
        print(f"PostgreSQL populado com sucesso (modo={args.mode})!")
    else:
        arq = popular_sqlite(caminho_banco=args.sqlite_path, incluir_casos_borda=sujo)
        print(f"Banco SQLite '{arq.name}' atualizado e populado com sucesso (modo={args.mode})!")


if __name__ == "__main__":
    main()
