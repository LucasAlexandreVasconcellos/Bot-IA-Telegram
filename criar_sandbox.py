import sqlite3

conexao = sqlite3.connect("sandbox_jarvis.db")
cursor = conexao.cursor()

# 1. Tabela de Indicadores Gerais
cursor.execute('''
CREATE TABLE IF NOT EXISTS indicadores_empresa (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    departamento TEXT,
    metrica TEXT,
    tipo_periodo TEXT,
    periodo TEXT,
    valor_monetario REAL,
    variacao REAL
)
''')

# 2. Nova Tabela de Vendas por Loja e Linha de Produtos (Para o exemplo de lojas/linhas)
cursor.execute('''
CREATE TABLE IF NOT EXISTS vendas_lojas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loja TEXT,
    linha_produto TEXT,
    ano INTEGER,
    mes TEXT,
    valor_venda REAL
)
''')

cursor.execute('DELETE FROM indicadores_empresa')
cursor.execute('DELETE FROM vendas_lojas')

# Dados Corporativos
dados_indicadores = [
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
    ("Financeiro", "Faturamento Líquido", "Semanal", "Semana 4 - Ago/2026", 3.0, -14.2)
]

# Dados de Lojas e Linhas de Produtos (Casual, Esportivo, Formal)
dados_vendas = [
    # Ano 2026 - Linha Casual
    ("Loja Centro", "Casual", 2026, "Janeiro/2026", 120000.0),
    ("Loja Shopping Sul", "Casual", 2026, "Janeiro/2026", 185000.0),
    ("Loja Norte", "Casual", 2026, "Janeiro/2026", 140000.0),
    ("Loja Oeste", "Casual", 2026, "Janeiro/2026", 95000.0),
    ("Loja Centro", "Casual", 2026, "Fevereiro/2026", 130000.0),
    ("Loja Shopping Sul", "Casual", 2026, "Fevereiro/2026", 190000.0),
    ("Loja Norte", "Casual", 2026, "Fevereiro/2026", 155000.0),
    ("Loja Oeste", "Casual", 2026, "Fevereiro/2026", 105000.0),
    
    # Linha Esportiva e Formal para comparação
    ("Loja Centro", "Esportivo", 2026, "Janeiro/2026", 85000.0),
    ("Loja Shopping Sul", "Esportivo", 2026, "Janeiro/2026", 110000.0),
    ("Loja Centro", "Formal", 2026, "Janeiro/2026", 90000.0),
    ("Loja Shopping Sul", "Formal", 2026, "Janeiro/2026", 125000.0)
]

cursor.executemany('''
INSERT INTO indicadores_empresa (departamento, metrica, tipo_periodo, periodo, valor_monetario, variacao)
VALUES (?, ?, ?, ?, ?, ?)
''', dados_indicadores)

cursor.executemany('''
INSERT INTO vendas_lojas (loja, linha_produto, ano, mes, valor_venda)
VALUES (?, ?, ?, ?, ?)
''', dados_vendas)

conexao.commit()
conexao.close()
print("Banco de dados 'sandbox_jarvis.db' atualizado e populado com sucesso!")
