import sqlite3
from mcp.server.fastmcp import FastMCP

# Criação da instância do servidor MCP
mcp = FastMCP("Servidor Banco Jarvis")
DB_PATH = "sandbox_jarvis.db"

@mcp.tool()
def listar_tabelas() -> str:
    """Lista todas as tabelas registadas na base de dados SQLite."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tabelas = [row[0] for row in cursor.fetchall() if row[0] != "sqlite_sequence"]
        conn.close()
        return f"Tabelas disponíveis: {', '.join(tabelas)}"
    except Exception as e:
        return f"Erro ao listar tabelas: {e}"

@mcp.tool()
def obter_esquema_tabela(nome_tabela: str) -> str:
    """Retorna as colunas e os tipos de dados de uma tabela específica."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({nome_tabela});")
        colunas = [f"{row[1]} ({row[2]})" for row in cursor.fetchall()]
        conn.close()
        if not colunas:
            return f"A tabela '{nome_tabela}' não foi encontrada."
        return f"Esquema de {nome_tabela}: " + ", ".join(colunas)
    except Exception as e:
        return f"Erro ao obter esquema: {e}"

@mcp.tool()
def executar_consulta_sql(query: str) -> str:
    """Executa apenas consultas SELECT de leitura na base de dados."""
    query_limpa = query.strip().strip("`").replace("sql", "").strip()
    if not query_limpa.upper().startswith("SELECT"):
        return "Erro: Apenas instruções de leitura (SELECT) são permitidas pelo protocolo de segurança."
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(query_limpa)
        colunas = [desc[0] for desc in cursor.description]
        linhas = cursor.fetchall()
        conn.close()

        if not linhas:
            return "Nenhum dado encontrado para a consulta informada."

        resultado = [dict(zip(colunas, linha)) for linha in linhas]
        return str(resultado)
    except Exception as e:
        return f"Falha na execução da consulta SQL: {e}"

if __name__ == "__main__":

    mcp.run(transport="stdio")
