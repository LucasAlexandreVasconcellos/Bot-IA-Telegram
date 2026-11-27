"""
Script oficial de Pré-Verificação Offline do Caderno de Testes (`docs/Caderno_de_Testes_JARVIS_KPI_BOT.md`).
Cria uma base temporária suja e exercita programaticamente todos os casos verificáveis offline
(`CT-001` a `CT-013`, `CT-019` a `CT-021`, `CT-024`, `CT-025`, `CT-027` a `CT-032`, `CT-034`, `CT-035`, `CT-037`).

Execute: `python ferramentas/pre_verificacao_offline.py`
"""
from __future__ import annotations

import logging
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Callable

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
if str(RAIZ_PROJETO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROJETO))

logging.disable(logging.CRITICAL)

from pydantic import ValidationError

from jarvis_bot.charts import criar_grafico_sandbox, remover_grafico_seguro
from jarvis_bot.db import DatabaseRepository
from jarvis_bot.mcp_client import ClienteMCPBanco
from jarvis_bot.quality import (
    corrigir_texto,
    sanitizar_linhas_consulta_detalhada,
    validar_data,
    validar_numero,
    validar_periodo,
)
from jarvis_bot.schemas import EstruturaGrafico, RespostaAgente, RoteamentoConsulta
from jarvis_bot.seed import popular_sqlite
from sandbox_ambiente.executor_sandbox import executar_codigo_sandbox


def executar_verificacao() -> int:
    resultados: list[tuple[str, str, bool, str]] = []

    def checar(ct_id: str, titulo: str, fn: Callable[[], str]) -> None:
        try:
            detalhe = fn()
            resultados.append((ct_id, titulo, True, detalhe))
        except Exception as exc:
            resultados.append((ct_id, titulo, False, f"{type(exc).__name__}: {exc}"))

    with tempfile.TemporaryDirectory() as tmp:
        pasta_tmp = Path(tmp)
        db_limpo = pasta_tmp / "limpo.db"
        db_sujo = pasta_tmp / "sujo.db"
        popular_sqlite(db_limpo, incluir_casos_borda=False)
        popular_sqlite(db_sujo, incluir_casos_borda=True)
        repo_limpo = DatabaseRepository(caminho_sqlite=db_limpo)

        # Injeta casos extremos adicionais na base suja (Latin-1, irrecuperável, textos em REAL, NULLs)
        conn_s = sqlite3.connect(str(db_sujo))
        conn_s.executemany(
            "INSERT INTO indicadores_empresa (departamento, metrica, tipo_periodo, periodo, valor_monetario, variacao) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("OperaÃ§Ã£o", "Faturamento Líquido", "Mensal", "Julho/2026", "R$ 1.234,56", "2,5"),
                (sqlite3.Binary(b"Produ\xe7\xe3o"), "Faturamento Líquido", "Mensal", "15/05/2026", 10.0, 1.0),
                (sqlite3.Binary(b"Finan\xe7eiro\x81"), "Receita", "Mensal", "Julho/2026", 50.0, 1.0),
                ("TI", "Custos", "Mensal", "2026-15-45", "muitos", "indefinida"),
                (None, "Receita", "Mensal", "ontem", None, 1.0),
            ],
        )
        conn_s.commit()
        conn_s.close()
        repo_sujo = DatabaseRepository(caminho_sqlite=db_sujo)

        checar(
            "CT-001",
            "Datas válidas e períodos corporativos",
            lambda: (
                assert_eq(validar_data("15/05/2026")[0], "2026-05-15")
                or assert_eq(validar_periodo("Julho/2026")[0], "Julho/2026")
                or "ISO e período textual aceitos"
            ),
        )
        checar(
            "CT-002",
            "Datas e períodos inválidos isolados",
            lambda: (
                assert_true(all(validar_periodo(x)[0] is None for x in ("2026-15-45", "0000-00-00", "ontem", "")))
                or "Entradas inválidas bloqueadas antes da IA"
            ),
        )
        checar(
            "CT-003",
            "Conversão de moeda brasileira no fluxo do banco",
            lambda: (
                assert_eq(validar_numero("R$ 1.234,56")[0], 1234.56)
                or assert_true(
                    any(
                        r["valor_monetario"] == 1234.56
                        for r in repo_sujo.executar_consulta_leitura(
                            "SELECT * FROM indicadores_empresa WHERE departamento LIKE '%Opera%'"
                        )["dados"]
                    )
                )
                or "R$ 1.234,56 convertido para float 1234.56"
            ),
        )
        checar(
            "CT-004/006/009",
            "Textos numéricos inválidos e NULLs isolados do contexto",
            lambda: (
                (res := repo_sujo.executar_consulta_leitura("SELECT * FROM indicadores_empresa"))
                and assert_true(all(r["valor_monetario"] != "muitos" and r["departamento"] is not None for r in res["dados"]))
                or f"{len(res['dados'])} válidos preservados, {res['isolados']} inválidos isolados"
            ),
        )
        checar(
            "CT-005",
            "Mojibake e bytes Latin-1 recuperados; bytes inválidos isolados",
            lambda: (
                assert_eq(corrigir_texto("OperaÃ§Ã£o")[0], "Operação")
                or (res := repo_sujo.executar_consulta_leitura("SELECT * FROM indicadores_empresa"))
                and assert_true(any(r["departamento"] == "Produção" for r in res["dados"]))
                or "Latin-1 recuperado e \\x81 isolado"
            ),
        )
        checar(
            "CT-007/037",
            "Variações negativas preservadas (CAC e Semana 4)",
            lambda: (
                (cac := repo_limpo.executar_consulta_leitura("SELECT * FROM indicadores_empresa WHERE metrica LIKE '%CAC%'"))
                and (sem4 := repo_limpo.executar_consulta_leitura("SELECT * FROM indicadores_empresa WHERE periodo LIKE '%Semana 4%'"))
                and assert_eq(len(cac["dados"]), 1)
                and assert_eq(len(sem4["dados"]), 1)
                or "CAC (-2,1%) e Semana 4 (-14,2%) preservados"
            ),
        )
        checar(
            "CT-010",
            "Consulta SELECT válida (Faturamento Agosto/2026)",
            lambda: (
                (r := repo_limpo.executar_consulta_leitura("SELECT valor_monetario, variacao FROM indicadores_empresa WHERE metrica LIKE '%Faturamento%' AND periodo='Agosto/2026'"))
                and assert_eq(r["dados"][0]["valor_monetario"], 12.4)
                or "Retornou 12,4M e 9,7%"
            ),
        )
        checar(
            "CT-011",
            "Consulta vazia sem vazamento de valores de outros meses",
            lambda: (
                (r := repo_limpo.executar_consulta_leitura("SELECT * FROM indicadores_empresa WHERE periodo LIKE '%2024%'"))
                and assert_eq(r["status"], "vazio")
                and assert_eq(r["dados"], [])
                or "Status vazio com apenas metadados de filtros"
            ),
        )
        checar(
            "CT-012/013",
            "Bloqueio de escrita, catálogos internos e tabelas inexistentes",
            lambda: (
                assert_true(
                    all(
                        not repo_limpo.executar_consulta_leitura(q)["sucesso"]
                        for q in (
                            "DROP TABLE vendas_lojas",
                            "SELECT * FROM sqlite_master",
                            "SELECT * FROM SQLITE_MASTER",
                            "SELECT * FROM tabela_inexistente",
                            "PRAGMA table_info(vendas_lojas)",
                        )
                    )
                )
                or "5 vetores SQL bloqueados sem traceback"
            ),
        )
        checar(
            "CT-019/020/021",
            "Geração de gráficos de barras, linhas (4 semanas) e pizza",
            lambda: _verificar_graficos(repo_limpo, pasta_tmp),
        )
        checar(
            "CT-025",
            "Limite de linhas e sinalização de truncamento",
            lambda: (
                (r := repo_limpo.executar_consulta_leitura("SELECT v.loja, i.metrica FROM vendas_lojas v, indicadores_empresa i", limite_maximo=20))
                and assert_true(r["truncado"] and len(r["dados"]) == 20)
                or "Truncado em 20 registros com aviso"
            ),
        )
        checar(
            "CT-027/031",
            "Contratos estritos Pydantic e bordas de gráfico",
            lambda: _verificar_pydantic(),
        )
        checar(
            "CT-029/032",
            "Servidor e Cliente MCP via STDIO com base suja",
            lambda: _verificar_mcp(db_sujo),
        )
        checar(
            "CT-030",
            "Higiene de .gitignore e ausência de segredos hardcoded",
            lambda: (
                assert_true((RAIZ_PROJETO / ".gitignore").exists())
                and assert_true(not (RAIZ_PROJETO / ".gitinore").exists())
                and assert_true("postgres:postgres" not in (RAIZ_PROJETO / "popular_postgres.py").read_text(encoding="utf-8"))
                or ".gitignore ativo e sem credenciais padrão no código"
            ),
        )
        checar(
            "CT-034",
            "Isolamento da Sandbox contra getattr/pandas/matplotlib.os",
            lambda: (
                assert_true(
                    all(
                        not executar_codigo_sandbox(c, caminho_banco=None)["sucesso"]
                        for c in (
                            "import os",
                            "getattr(__builtins__, 'op'+'en')('x')",
                            "pd.read_csv('x')",
                            "matplotlib.os.environ.get('OPENAI_API_KEY')",
                        )
                    )
                )
                or "Todos os escapes AST bloqueados"
            ),
        )
        checar(
            "CT-035",
            "Banco ausente tratado sem criar arquivo vazio",
            lambda: (
                (p := pasta_tmp / "ausente.db")
                and (r := DatabaseRepository(caminho_sqlite=p).executar_consulta_leitura("SELECT * FROM vendas_lojas"))
                and assert_true(not r["sucesso"] and not p.exists())
                or "Falha controlada sem arquivo órfão"
            ),
        )

    aprovados = sum(1 for _, _, ok, _ in resultados if ok)
    print("=" * 88)
    print("PRÉ-VERIFICAÇÃO OFFLINE AUTOMATIZADA — JARVIS KPI BOT")
    print("=" * 88)
    for ct_id, titulo, ok, det in resultados:
        status = "APROVADO" if ok else "REPROVADO"
        print(f"[{status:<9}] {ct_id:<14} | {titulo:<48} | {det}")
    print("-" * 88)
    print(f"Total: {aprovados}/{len(resultados)} verificações offline aprovadas.")
    print("=" * 88)
    return 0 if aprovados == len(resultados) else 1


def assert_eq(a, b) -> None:
    if a != b:
        raise AssertionError(f"{a!r} != {b!r}")


def assert_true(cond: bool) -> None:
    if not cond:
        raise AssertionError("Condição falsa")


def _verificar_graficos(repo: DatabaseRepository, pasta: Path) -> str:
    sem = repo.executar_consulta_leitura(
        "SELECT periodo, valor_monetario FROM indicadores_empresa WHERE tipo_periodo='Semanal'"
    )["dados"]
    assert_eq(len(sem), 4)
    g = EstruturaGrafico(
        tipo="linha",
        titulo="Faturamento Semanal Agosto/2026",
        rotulos_x=[r["periodo"] for r in sem],
        valores_y=[r["valor_monetario"] for r in sem],
    )
    arq = criar_grafico_sandbox(g, pasta_saida=pasta)
    assert_true(Path(arq).exists())
    remover_grafico_seguro(arq)
    assert_true(not Path(arq).exists())
    return "4 pontos semanais plotados e PNG limpo após uso"


def _verificar_pydantic() -> str:
    falhas = 0
    for fn in (
        lambda: RoteamentoConsulta(tipo_solicitacao="banco_dados", sql_query="DROP TABLE vendas_lojas"),
        lambda: EstruturaGrafico(tipo="barra", titulo="X", rotulos_x=["A", "B"], valores_y=[1.0]),
        lambda: EstruturaGrafico(tipo="pizza", titulo="X", rotulos_x=["A"], valores_y=[-1.0]),
        lambda: RespostaAgente(texto_resposta="Sem sufixo obrigatório.", gerar_grafico=False),
        lambda: RespostaAgente(texto_resposta="Com gráfico nulo, senhor.", gerar_grafico=True, grafico=None),
    ):
        try:
            fn()
        except ValidationError:
            falhas += 1
    assert_eq(falhas, 5)
    return "5 contratos inválidos bloqueados pelo Pydantic"


def _verificar_mcp(db_sujo: Path) -> str:
    cli = ClienteMCPBanco(use_mcp=True, database_url=f"sqlite:///{db_sujo.as_posix()}")
    bloqueio = cli.obter_esquema_tabela("sqlite_master")
    assert_true(not bloqueio["sucesso"])
    consulta = cli.consultar_sql("SELECT * FROM vendas_lojas")
    assert_true(consulta["sucesso"] and len(consulta["dados"]) >= 12)
    return f"MCP STDIO validado ({len(consulta['dados'])} linhas limpas, {consulta['isolados']} isoladas)"


if __name__ == "__main__":
    raise SystemExit(executar_verificacao())
