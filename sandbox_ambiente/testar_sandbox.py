import sys
from pathlib import Path

# Garante que o Python enxergue a raiz do projeto para achar o sandbox_jarvis.db
raiz_projeto = Path(__file__).resolve().parent.parent
sys.path.append(str(raiz_projeto))

from sandbox_ambiente.executor_sandbox import executar_codigo_sandbox

banco_path = str(raiz_projeto / "sandbox_jarvis.db")
charts_path = str(raiz_projeto / "charts")

print("=== TESTE 1: Execução Segura (SQL + Pandas + Gráfico) ===")
codigo_seguro = """
conn = sqlite3.connect('dados_sandbox.db')
df = pd.read_sql_query("SELECT loja, valor_venda FROM vendas_lojas WHERE linha_produto = 'Casual' AND mes = 'Janeiro/2026'", conn)
print("Tabela extraída na Sandbox:")
print(df)

plt.figure(figsize=(8, 5))
plt.bar(df['loja'], df['valor_venda'], color='#2b5c8f')
plt.title('Vendas Linha Casual - Janeiro/2026')
plt.ylabel('Valor de Venda (R$)')
plt.tight_layout()
plt.savefig('vendas_casual_jan2026.png')
"""

res1 = executar_codigo_sandbox(codigo_seguro, caminho_banco=banco_path, pasta_saida_graficos=charts_path)
print("Status:", res1["sucesso"])
print("Saída:\n", res1["saida"])
print("Gráfico salvo em:", res1["grafico_gerado"])
if res1["erro"]:
    print("Erro:", res1["erro"])

print("\n=== TESTE 2: Bloqueio de Segurança (Tentativa de invadir o Windows) ===")
codigo_malicioso = """
import os
print(os.listdir('C:/'))
"""

res2 = executar_codigo_sandbox(codigo_malicioso)
print("Status:", res2["sucesso"])
print("Bloqueio acionado:", res2["erro"])