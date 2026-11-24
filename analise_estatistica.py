
import sqlite3
import pandas as pd
from uuid import uuid4
from contextlib import closing

from qualidade_dados import sanitizar_linhas_consulta
from sandbox_ambiente.executor_sandbox import executar_codigo_sandbox


def gerar_analise_estatistica(dados, coluna, titulo="Análise Estatística"):

    df = pd.DataFrame(dados)

    if df.empty or coluna not in df.columns:
        raise ValueError("Dados insuficientes para análise.")

    serie = pd.to_numeric(df[coluna], errors="coerce")
    serie = serie.replace([float("inf"), float("-inf")], float("nan"))
    serie = serie.dropna().astype(float)

    if serie.empty:
        raise ValueError("Nenhum valor numérico válido encontrado.")

    resumo = {
        "quantidade": int(serie.count()),
        "media": float(serie.mean()),
        "mediana": float(serie.median()),
        "desvio_padrao": float(serie.std(ddof=0)),
        "minimo": float(serie.min()),
        "maximo": float(serie.max()),
        "descartados": len(df) - len(serie)
    }

    nome_arquivo = f"estatistica_{uuid4().hex}.png"

    codigo_grafico = f"""
import seaborn as sns

valores = {repr(serie.tolist())}
coluna = {repr(coluna)}
titulo = {repr(titulo)}

sns.set_theme(style="whitegrid")

fig, eixos = plt.subplots(2, 1, figsize=(10, 8))

# Histograma
sns.histplot(
    x=valores,
    bins="auto",
    color="steelblue",
    ax=eixos[0]
)

eixos[0].set_title("Distribuição dos valores")
eixos[0].set_xlabel(coluna)
eixos[0].set_ylabel("Frequência")

# Boxplot
sns.boxplot(
    x=valores,
    color="seagreen",
    ax=eixos[1]
)

eixos[1].set_title("Boxplot dos valores")
eixos[1].set_xlabel(coluna)

fig.suptitle(titulo, fontsize=16, fontweight="bold")
fig.tight_layout(rect=(0, 0, 1, 0.95))
fig.savefig({repr(nome_arquivo)}, dpi=160)
plt.close(fig)
"""

    resultado = executar_codigo_sandbox(
        codigo_python=codigo_grafico,
        pasta_saida_graficos="charts",
        timeout_segundos=30
    )

    if not resultado["sucesso"] or not resultado["grafico_gerado"]:
        raise RuntimeError(
            f"Erro ao gerar gráfico: {resultado['erro']}"
        )

    return resumo, resultado["grafico_gerado"]


# Teste local sem depender da API da OpenAI
if __name__ == "__main__":

    with closing(sqlite3.connect(
        "file:sandbox_jarvis.db?mode=ro", uri=True
    )) as conexao:

        conexao.row_factory = sqlite3.Row
        conexao.text_factory = bytes

        registros = conexao.execute(
            "SELECT * FROM vendas_lojas"
        ).fetchall()

        dados = [dict(registro) for registro in registros]

    dados, isolados = sanitizar_linhas_consulta(dados)

    resumo, imagem = gerar_analise_estatistica(
        dados,
        coluna="valor_venda",
        titulo="Análise Estatística de Vendas"
    )

    print("\n--- RESULTADO DA ANÁLISE ---\n")

    for chave, valor in resumo.items():
        print(f"{chave}: {valor:.2f}")

    print(f"Registros isolados: {isolados}")
    print(f"\nGráfico salvo em: {imagem}")
