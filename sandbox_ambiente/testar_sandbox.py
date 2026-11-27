"""
Script de demonstração da Sandbox Python blindada (`sandbox_ambiente/executor_sandbox.py`).
Execute: `python sandbox_ambiente/testar_sandbox.py`
"""
from __future__ import annotations

import sys
from pathlib import Path

raiz_projeto = Path(__file__).resolve().parent.parent
if str(raiz_projeto) not in sys.path:
    sys.path.insert(0, str(raiz_projeto))

from jarvis_bot.charts import remover_grafico_seguro
from jarvis_bot.seed import popular_sqlite
from sandbox_ambiente.executor_sandbox import executar_codigo_sandbox


def demonstrar_sandbox() -> None:
    banco_path = popular_sqlite(incluir_casos_borda=False)
    charts_path = str(raiz_projeto / "charts")

    print("=== TESTE 1: Execução Segura (SQLite + Matplotlib na Sandbox) ===")
    codigo_seguro = """
conn = sqlite3.connect('dados_sandbox.db')
cur = conn.cursor()
cur.execute(
    "SELECT loja, valor_venda FROM vendas_lojas "
    "WHERE linha_produto = 'Casual' AND mes = 'Janeiro/2026' ORDER BY loja"
)
linhas = cur.fetchall()
conn.close()

lojas = [r[0] for r in linhas]
valores = [r[1] for r in linhas]
print("Registros extraídos na Sandbox:", len(linhas))

plt.figure(figsize=(8, 5))
plt.bar(lojas, valores, color='#2b5c8f')
plt.title('Vendas Linha Casual - Janeiro/2026')
plt.ylabel('Valor de Venda (R$)')
plt.tight_layout()
plt.savefig('demo_vendas_casual_jan2026.png')
plt.close()
"""
    res1 = executar_codigo_sandbox(
        codigo_seguro,
        caminho_banco=str(banco_path),
        pasta_saida_graficos=charts_path,
    )
    print("Status:", res1["sucesso"])
    print("Saída:", res1["saida"])
    print("Gráfico gerado:", res1["grafico_gerado"])
    remover_grafico_seguro(res1["grafico_gerado"])

    print("\n=== TESTE 2: Bloqueio de Segurança (Tentativas de Escape AST) ===")
    for tentativa in (
        "import os\nprint(os.listdir('C:/'))",
        "getattr(__builtins__, 'op'+'en')('dados.txt')",
        "print(matplotlib.os.environ.get('OPENAI_API_KEY'))",
    ):
        res_bloq = executar_codigo_sandbox(tentativa, caminho_banco=None)
        print(f"Status={res_bloq['sucesso']} | Bloqueio={res_bloq['erro']}")


if __name__ == "__main__":
    demonstrar_sandbox()
