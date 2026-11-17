import ast
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

# Módulos bloqueados por segurança (impede acesso ao sistema operacional e rede)
MODULOS_PROIBIDOS = {
    "os", "sys", "subprocess", "shutil", "socket", "requests", 
    "urllib", "http", "ftplib", "telnetlib", "pty", "pathlib", "importlib"
}

# Funções embutidas bloqueadas
FUNCOES_PROIBIDAS = {"eval", "exec", "compile", "__import__", "open", "input"}

class SandboxSecurityError(Exception):
    """Exceção levantada quando o código da IA viola regras de segurança."""
    pass

def validar_seguranca_codigo(codigo: str) -> None:
    """Analisa a árvore sintática (AST) do código Python antes de executar."""
    try:
        arvore = ast.parse(codigo)
    except SyntaxError as e:
        raise SandboxSecurityError(f"Erro de sintaxe no código gerado: {e}")

    for node in ast.walk(arvore):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modulo_base = alias.name.split('.')[0]
                if modulo_base in MODULOS_PROIBIDOS:
                    raise SandboxSecurityError(f"Importação bloqueada por segurança: '{modulo_base}'")
        
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modulo_base = node.module.split('.')[0]
                if modulo_base in MODULOS_PROIBIDOS:
                    raise SandboxSecurityError(f"Importação bloqueada por segurança: '{modulo_base}'")

        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in FUNCOES_PROIBIDAS:
                raise SandboxSecurityError(f"Função bloqueada por segurança: '{node.func.id}()'")

def executar_codigo_sandbox(
    codigo_python: str, 
    caminho_banco: str = "sandbox_jarvis.db", 
    pasta_saida_graficos: str = "charts",
    timeout_segundos: int = 15
) -> dict:
    """
    Executa código Python gerado pela IA em um diretório temporário isolado.
    """
    # 1. Validação estática de segurança
    try:
        validar_seguranca_codigo(codigo_python)
    except SandboxSecurityError as sec_err:
        return {
            "sucesso": False,
            "saida": "",
            "erro": str(sec_err),
            "grafico_gerado": None
        }

    # 2. Cria diretório temporário isolado
    dir_temporario = tempfile.mkdtemp(prefix="jarvis_sandbox_")
    dir_charts_destino = Path(pasta_saida_graficos)
    dir_charts_destino.mkdir(exist_ok=True)

    try:
        # Copia o banco de dados para dentro da sandbox (protege o banco original)
        banco_origem = Path(caminho_banco)
        if banco_origem.exists():
            shutil.copy2(banco_origem, Path(dir_temporario) / "dados_sandbox.db")

        # Cabeçalho padrão para análise de dados e gráficos sem abrir janela (Agg)
        cabecalho_seguro = (
            "import matplotlib\n"
            "matplotlib.use('Agg')\n"
            "import matplotlib.pyplot as plt\n"
            "import sqlite3\n"
            "import pandas as pd\n\n"
        )
        script_completo = cabecalho_seguro + codigo_python

        arquivo_script = Path(dir_temporario) / "script_ia.py"
        arquivo_script.write_text(script_completo, encoding="utf-8")

        # 3. Executa o código em subprocesso isolado com limite de tempo
        processo = subprocess.run(
            [sys.executable, str(arquivo_script)],
            cwd=dir_temporario,
            capture_output=True,
            text=True,
            timeout=timeout_segundos
        )

        # 4. Resgata o gráfico (.png) gerado, se houver
        caminho_grafico_final = None
        for arquivo in Path(dir_temporario).glob("*.png"):
            destino = dir_charts_destino / arquivo.name
            shutil.copy2(arquivo, destino)
            caminho_grafico_final = str(destino)
            break

        if processo.returncode == 0:
            return {
                "sucesso": True,
                "saida": processo.stdout.strip(),
                "erro": "",
                "grafico_gerado": caminho_grafico_final
            }
        else:
            return {
                "sucesso": False,
                "saida": processo.stdout.strip(),
                "erro": processo.stderr.strip(),
                "grafico_gerado": None
            }

    except subprocess.TimeoutExpired:
        return {
            "sucesso": False,
            "saida": "",
            "erro": f"Timeout: O script excedeu {timeout_segundos} segundos e foi encerrado.",
            "grafico_gerado": None
        }
    except Exception as e:
        return {
            "sucesso": False,
            "saida": "",
            "erro": f"Erro interno na sandbox: {str(e)}",
            "grafico_gerado": None
        }
    finally:
        # 5. Apaga a pasta temporária após a execução
        shutil.rmtree(dir_temporario, ignore_errors=True)