import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

# Pega a URL do PostgreSQL definida no arquivo .env
DATABASE_URL = os.getenv("POSTGRES_URL", "postgresql://postgres:postgres@localhost:5432/postgres")

def popular_postgres():
    print("Conectando ao PostgreSQL...")
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()

    # 1. Criação das Tabelas no dialeto PostgreSQL (SERIAL, NUMERIC, VARCHAR)
    cursor.execute("""
    DROP TABLE IF EXISTS vendas_lojas;
    DROP TABLE IF EXISTS indicadores_empresa;

    CREATE TABLE indicadores_empresa (
        id SERIAL PRIMARY KEY,
        departamento VARCHAR(100),
        metrica VARCHAR(150),
        tipo_periodo VARCHAR(50),
        periodo VARCHAR(100),
        valor_monetario NUMERIC(15, 2),
        variacao NUMERIC(6, 2)
    );

    CREATE TABLE vendas_lojas (
        id SERIAL PRIMARY KEY,
        loja VARCHAR(150),
        linha_produto VARCHAR(100),
        ano INT,
        mes VARCHAR(100),
        valor_venda NUMERIC(15, 2)
    );
    """)

    # 2. Dados Corporativos de Indicadores
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

    # 3. Base de Vendas: Dados Originais + Volume Expandido + Casos de Borda
    dados_vendas = [
        # --- SEUS DADOS BASE (2026) ---
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

        # --- EXPANSÃO DE VOLUME (Mais meses e filiais) ---
        ("Loja Centro", "Casual", 2026, "Março/2026", 142000.0),
        ("Loja Shopping Sul", "Casual", 2026, "Março/2026", 210000.0),
        ("Loja Norte", "Casual", 2026, "Março/2026", 160000.0),
        ("Loja Oeste", "Casual", 2026, "Março/2026", 112000.0),
        ("Loja Taguatinga", "Casual", 2026, "Janeiro/2026", 98000.0),
        ("Loja Taguatinga", "Casual", 2026, "Fevereiro/2026", 102000.0),
        ("Loja Taguatinga", "Casual", 2026, "Março/2026", 115000.0),
        ("Loja Águas Claras", "Casual", 2026, "Janeiro/2026", 175000.0),
        ("Loja Águas Claras", "Casual", 2026, "Fevereiro/2026", 182000.0),

        # --- CASOS DE BORDA E DADOS QUEBRADOS (Para atender ao requisito) ---
        # 1. Erros de codificação de caracteres (Mojibake / UTF-8 corrompido)
        ("Loja PromoÃ§Ã£o_Quebrada", "Casual", 2026, "Janeiro/2026", 45000.0),
        ("Loja Sudoeste â€• Filial", "Casual", 2026, "Fevereiro/2026", 78000.0),
        ("Loja Centro", "ColeÃ§Ã£o_Inverno", 2026, "Janeiro/2026", 62000.0),

        # 2. Valores negativos (estorno, devolução ou erro de input sem sanitização)
        ("Loja Devolucoes_Gerais", "Casual", 2026, "Janeiro/2026", -32000.0),
        ("Loja Centro", "Casual", 2026, "Fevereiro/2026", -5000.0),

        # 3. Loja inativa ou venda zerada
        ("Loja Reforma Fechada", "Casual", 2026, "Janeiro/2026", 0.0),

        # 4. Inconsistência de formato de texto na data
        ("Loja Centro", "Casual", 2026, "2026-04-XX_DATA_CORROMPIDA", 55000.0),

        # 5. Outlier extremo
        ("Loja Erro Digitação", "Casual", 2026, "Janeiro/2026", 99999999.0)
    ]

    # Inserção com sintaxe do Postgres (%s)
    cursor.executemany("""
    INSERT INTO indicadores_empresa (departamento, metrica, tipo_periodo, periodo, valor_monetario, variacao)
    VALUES (%s, %s, %s, %s, %s, %s)
    """, dados_indicadores)

    cursor.executemany("""
    INSERT INTO vendas_lojas (loja, linha_produto, ano, mes, valor_venda)
    VALUES (%s, %s, %s, %s, %s)
    """, dados_vendas)

    conn.commit()
    cursor.close()
    conn.close()
    print("PostgreSQL configurado e populado com sucesso (incluindo casos de borda)!")

if __name__ == "__main__":
    popular_postgres()
