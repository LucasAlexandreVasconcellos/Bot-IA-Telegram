"""
Sandbox isolada para execução restrita de scripts analíticos e renderização de gráficos.
Blindagens implementadas (DEF-014 / CT-034 / DEF-016):
- Allowlist estrita de módulos permitidos (substitui blocklist parcial).
- Bloqueio em AST de chamadas perigosas (`open`, `getattr`, `eval`, `exec`, `__import__`, etc.),
  identificadores dunder (`__builtins__`, `__subclasses__`, `__globals__`) e atributos de I/O externo
  ou acesso indireto ao SO (`matplotlib.os`, `pd.read_csv`, `np.load`, `environ`, etc.).
- Subprocesso Python executado com flag `-E` e dicionário `env` mínimo higienizado (sem vazar
  `OPENAI_API_KEY`, `TELEGRAM_TOKEN` ou `DATABASE_URL`).
- Resolução segura de caminhos relativos a partir da raiz do projeto.
"""
from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

RAIZ_PROJETO = Path(__file__).resolve().parent.parent

MODULOS_PERMITIDOS = frozenset(
    {
        "math",
        "statistics",
        "json",
        "base64",
        "decimal",
        "fractions",
        "collections",
        "itertools",
        "functools",
        "datetime",
        "re",
        "numpy",
        "matplotlib",
        "sqlite3",
        "pandas",
    }
)

MODULOS_PROIBIDOS = frozenset(
    {
        "os",
        "sys",
        "subprocess",
        "shutil",
        "socket",
        "requests",
        "urllib",
        "http",
        "ftplib",
        "telnetlib",
        "pty",
        "pathlib",
        "importlib",
        "builtins",
        "ctypes",
        "io",
        "pickle",
        "marshal",
        "inspect",
        "gc",
        "code",
        "webbrowser",
        "multiprocessing",
        "threading",
    }
)

FUNCOES_PROIBIDAS = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
        "open",
        "input",
        "getattr",
        "setattr",
        "delattr",
        "globals",
        "locals",
        "vars",
        "dir",
        "breakpoint",
        "help",
        "memoryview",
    }
)

ATRIBUTOS_PROIBIDOS = frozenset(
    {
        "os",
        "sys",
        "subprocess",
        "shutil",
        "socket",
        "io",
        "builtins",
        "importlib",
        "environ",
        "getenv",
        "putenv",
        "popen",
        "system",
        "spawnl",
        "spawnle",
        "spawnv",
        "spawnve",
        "read_csv",
        "read_table",
        "read_fwf",
        "read_excel",
        "read_json",
        "read_html",
        "read_xml",
        "read_parquet",
        "read_orc",
        "read_feather",
        "read_pickle",
        "read_hdf",
        "to_csv",
        "to_pickle",
        "to_excel",
        "to_parquet",
        "loadtxt",
        "genfromtxt",
        "fromfile",
        "load",
        "save",
        "savez",
        "savez_compressed",
    }
)

_VARIAVEIS_SISTEMA_ESSENCIAIS = (
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "PATH",
    "PATHEXT",
    "LD_LIBRARY_PATH",
    "DYLD_LIBRARY_PATH",
    "LANG",
    "LC_ALL",
)


class SandboxSecurityError(Exception):
    """Exceção levantada quando o código submetido à sandbox viola políticas de segurança."""


def validar_seguranca_codigo(codigo: str) -> None:
    """Analisa a árvore sintática (AST) do código Python aplicando allowlist e bloqueio de introspecção."""
    if not isinstance(codigo, str) or not codigo.strip():
        raise SandboxSecurityError("Código vazio submetido à sandbox.")

    try:
        arvore = ast.parse(codigo)
    except SyntaxError as exc:
        raise SandboxSecurityError(f"Erro de sintaxe no código submetido: {exc}") from exc

    for node in ast.walk(arvore):
        if isinstance(node, ast.Import):
            for alias in node.names:
                partes = alias.name.split(".")
                modulo_base = partes[0]
                if modulo_base in MODULOS_PROIBIDOS or modulo_base not in MODULOS_PERMITIDOS:
                    raise SandboxSecurityError(
                        f"Importação bloqueada por segurança: '{alias.name}'"
                    )
                if any(p in MODULOS_PROIBIDOS for p in partes[1:]):
                    raise SandboxSecurityError(
                        f"Submódulo bloqueado por segurança: '{alias.name}'"
                    )

        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                raise SandboxSecurityError("Importações relativas não são permitidas na sandbox.")
            modulo_completo = node.module or ""
            partes = modulo_completo.split(".") if modulo_completo else []
            modulo_base = partes[0] if partes else ""
            if modulo_base in MODULOS_PROIBIDOS or modulo_base not in MODULOS_PERMITIDOS:
                raise SandboxSecurityError(
                    f"Importação bloqueada por segurança: '{modulo_completo}'"
                )
            for alias in node.names:
                if (
                    alias.name == "*"
                    or alias.name.startswith("_")
                    or alias.name in MODULOS_PROIBIDOS
                    or alias.name in ATRIBUTOS_PROIBIDOS
                    or alias.name in FUNCOES_PROIBIDAS
                ):
                    raise SandboxSecurityError(
                        f"Símbolo importado bloqueado por segurança: '{alias.name}'"
                    )

        elif isinstance(node, ast.Name):
            if node.id.startswith("__") or node.id.endswith("__"):
                raise SandboxSecurityError(
                    f"Acesso a identificador interno bloqueado: '{node.id}'"
                )
            if node.id in FUNCOES_PROIBIDAS:
                raise SandboxSecurityError(
                    f"Referência a função bloqueada por segurança: '{node.id}'"
                )

        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                raise SandboxSecurityError(
                    f"Acesso a atributo privado/dunder bloqueado: '{node.attr}'"
                )
            if node.attr in ATRIBUTOS_PROIBIDOS:
                raise SandboxSecurityError(
                    f"Acesso a atributo/método bloqueado por segurança: '{node.attr}'"
                )

        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in FUNCOES_PROIBIDAS:
                raise SandboxSecurityError(
                    f"Função bloqueada por segurança: '{node.func.id}()'"
                )


def _construir_env_sandbox(dir_temporario: str) -> dict[str, str]:
    """Cria ambiente limpo sem credenciais da aplicação (`OPENAI_API_KEY`, `TELEGRAM_TOKEN`, etc.)."""
    env_seguro: dict[str, str] = {}
    for chave in _VARIAVEIS_SISTEMA_ESSENCIAIS:
        val = os.environ.get(chave)
        if val:
            env_seguro[chave] = val

    env_seguro["TEMP"] = dir_temporario
    env_seguro["TMP"] = dir_temporario
    env_seguro["TMPDIR"] = dir_temporario
    env_seguro["HOME"] = dir_temporario
    env_seguro["USERPROFILE"] = dir_temporario
    env_seguro["MPLBACKEND"] = "Agg"
    env_seguro["MPLCONFIGDIR"] = dir_temporario
    env_seguro["PYTHONUTF8"] = "1"
    env_seguro["PYTHONDONTWRITEBYTECODE"] = "1"
    return env_seguro


def _resolver_caminho(caminho: str | Path, padrao_relativo: Path) -> Path:
    p = Path(caminho) if caminho else padrao_relativo
    if not p.is_absolute():
        p = (RAIZ_PROJETO / p).resolve()
    return p


def executar_codigo_sandbox(
    codigo_python: str,
    caminho_banco: str | None = "sandbox_jarvis.db",
    pasta_saida_graficos: str = "charts",
    timeout_segundos: int = 15,
) -> dict[str, Any]:
    """
    Executa código analítico/gráfico validado em diretório temporário isolado e ambiente higienizado.
    """
    try:
        validar_seguranca_codigo(codigo_python)
    except SandboxSecurityError as sec_err:
        return {
            "sucesso": False,
            "saida": "",
            "erro": str(sec_err),
            "grafico_gerado": None,
        }

    dir_temporario = tempfile.mkdtemp(prefix="jarvis_sandbox_")
    dir_charts_destino = _resolver_caminho(pasta_saida_graficos, RAIZ_PROJETO / "charts")
    dir_charts_destino.mkdir(parents=True, exist_ok=True)

    try:
        if caminho_banco:
            banco_origem = _resolver_caminho(caminho_banco, RAIZ_PROJETO / "sandbox_jarvis.db")
            if banco_origem.exists() and banco_origem.is_file():
                destino_db = Path(dir_temporario) / "dados_sandbox.db"
                shutil.copy2(banco_origem, destino_db)

        precisa_pandas = ("pd." in codigo_python) or ("pandas" in codigo_python)
        precisa_sqlite = ("sqlite3" in codigo_python) or bool(caminho_banco)

        linhas_cabecalho = [
            "import sys as _sys_io",
            "_sys_io.stdout.reconfigure(encoding='utf-8')",
            "del _sys_io",
            "import matplotlib",
            "matplotlib.use('Agg')",
            "import matplotlib.pyplot as plt",
        ]
        if precisa_sqlite:
            linhas_cabecalho.append("import sqlite3")
        if precisa_pandas:
            linhas_cabecalho.append("import pandas as pd")

        script_completo = "\n".join(linhas_cabecalho) + "\n\n" + codigo_python
        arquivo_script = Path(dir_temporario) / "script_ia.py"
        arquivo_script.write_text(script_completo, encoding="utf-8")

        processo = subprocess.run(
            [sys.executable, "-E", str(arquivo_script)],
            cwd=dir_temporario,
            env=_construir_env_sandbox(dir_temporario),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_segundos,
        )

        caminho_grafico_final = None
        if processo.returncode == 0:
            for arquivo in sorted(Path(dir_temporario).glob("*.png")):
                destino = dir_charts_destino / arquivo.name
                shutil.copy2(arquivo, destino)
                caminho_grafico_final = str(destino)
                break

        if processo.returncode == 0:
            return {
                "sucesso": True,
                "saida": processo.stdout.strip(),
                "erro": "",
                "grafico_gerado": caminho_grafico_final,
            }

        return {
            "sucesso": False,
            "saida": processo.stdout.strip(),
            "erro": "A execução do script na sandbox falhou.",
            "erro_interno": processo.stderr.strip(),
            "grafico_gerado": None,
        }

    except subprocess.TimeoutExpired:
        return {
            "sucesso": False,
            "saida": "",
            "erro": f"Timeout: O script excedeu {timeout_segundos} segundos e foi encerrado.",
            "grafico_gerado": None,
        }
    except Exception as exc:
        return {
            "sucesso": False,
            "saida": "",
            "erro": "Erro interno ao executar ambiente isolado.",
            "erro_interno": str(exc),
            "grafico_gerado": None,
        }
    finally:
        shutil.rmtree(dir_temporario, ignore_errors=True)
