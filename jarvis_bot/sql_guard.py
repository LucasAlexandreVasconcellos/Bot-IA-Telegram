"""
Validação estrutural e sintática de consultas SQL (`sqlglot` + fallback léxico).
Garante:
- Limpeza segura de cercas Markdown sem corromper substrings `'sql'` (DEF-005).
- Exatamente uma única instrução de leitura `SELECT` (DEF-004 / CT-012).
- Allowlist estrita de tabelas (`indicadores_empresa`, `vendas_lojas`) e bloqueio de
  tabelas/funções internas (`sqlite_master`, `pragma_*`, `pg_catalog`, `information_schema`) (CT-013).
- Aplicação de `LIMIT` máximo para proteger o contexto da IA contra produtos cartesianos (DEF-007 / CT-025).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from jarvis_bot.quality import LIMITE_LINHAS_CONTEXTO_IA

TABELAS_PERMITIDAS: frozenset[str] = frozenset({"indicadores_empresa", "vendas_lojas"})

_PALAVRAS_PROIBIDAS_SQL = frozenset(
    {
        "insert",
        "update",
        "delete",
        "drop",
        "alter",
        "create",
        "truncate",
        "replace",
        "attach",
        "detach",
        "vacuum",
        "pragma",
        "grant",
        "revoke",
        "reindex",
        "copy",
        "call",
        "execute",
        "merge",
        "upsert",
    }
)

_CATALOGOS_PROIBIDOS = (
    "sqlite_master",
    "sqlite_schema",
    "sqlite_temp_master",
    "sqlite_temp_schema",
    "sqlite_sequence",
    "pragma_",
    "pg_catalog",
    "pg_shadow",
    "pg_roles",
    "pg_authid",
    "pg_stat",
    "information_schema",
)

_RE_CERCA_INICIO = re.compile(r"^\s*```(?:sql|sqlite|postgresql|postgres)?\s*", re.IGNORECASE)
_RE_CERCA_FIM = re.compile(r"\s*```\s*$")
_RE_COMENTARIO_LINHA = re.compile(r"--[^\r\n]*")
_RE_COMENTARIO_BLOCO = re.compile(r"/\*.*?\*/", re.DOTALL)
_RE_LITERAL_ASPAS = re.compile(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"")


class SQLValidacaoErro(ValueError):
    """Exceção controlada levantada quando uma consulta SQL viola políticas de segurança."""


@dataclass(frozen=True)
class SQLValidado:
    sql_original_limpo: str
    sql_com_limite: str
    tabelas_referenciadas: tuple[str, ...]
    limite_efetivo: int


def limpar_markdown_sql(sql: str) -> str:
    """Remove apenas cercas de código Markdown e ponto-e-vírgula final, preservando literais como `%sql%`."""
    if not sql or not isinstance(sql, str):
        return ""
    limpo = _RE_CERCA_INICIO.sub("", sql.strip())
    limpo = _RE_CERCA_FIM.sub("", limpo).strip()
    while limpo.endswith(";"):
        limpo = limpo[:-1].rstrip()
    return limpo


def _mascarar_literais_e_comentarios(sql: str) -> str:
    """Remove comentários e substitui literais entre aspas por espaços para inspeção segura de tokens."""
    if "/*" in sql and "*/" not in sql:
        raise SQLValidacaoErro("Comentário de bloco SQL malformado.")
    sem_bloco = _RE_COMENTARIO_BLOCO.sub(" ", sql)
    sem_linha = _RE_COMENTARIO_LINHA.sub(" ", sem_bloco)
    return _RE_LITERAL_ASPAS.sub(" '' ", sem_linha)


def _validar_regras_lexicas_base(sql_limpo: str) -> str:
    if not sql_limpo:
        raise SQLValidacaoErro("Consulta SQL vazia.")

    mascarado = _mascarar_literais_e_comentarios(sql_limpo).strip()
    if not mascarado:
        raise SQLValidacaoErro("Consulta SQL sem instrução executável.")

    if ";" in mascarado:
        raise SQLValidacaoErro("Múltiplas instruções SQL não são permitidas.")

    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_$]*", mascarado)
    if not tokens:
        raise SQLValidacaoErro("Consulta SQL inválida.")

    primeiro = tokens[0].lower()
    if primeiro not in ("select", "with"):
        raise SQLValidacaoErro(
            "Apenas instruções de leitura (SELECT) são permitidas pelo protocolo de segurança."
        )

    mascarado_lower = mascarado.lower()
    for catalogo in _CATALOGOS_PROIBIDOS:
        if catalogo in mascarado_lower:
            raise SQLValidacaoErro(
                "Acesso a tabelas de catálogo ou funções internas do banco não é permitido."
            )

    for tok in tokens:
        tl = tok.lower()
        if tl in _PALAVRAS_PROIBIDAS_SQL:
            raise SQLValidacaoErro(
                f"Operação SQL bloqueada pela política de somente leitura: '{tok.upper()}'."
            )

    return mascarado


def _validar_com_sqlglot(
    sql_limpo: str,
    dialeto_leitura: str,
    dialeto_escrita: str,
    limite_maximo: int,
    permitir_select_constante: bool,
) -> SQLValidado:
    import sqlglot
    from sqlglot import exp

    try:
        expressoes = sqlglot.parse(sql_limpo, read=dialeto_leitura)
    except Exception as exc:
        raise SQLValidacaoErro("Erro de sintaxe na consulta SQL gerada.") from exc

    expressoes = [e for e in expressoes if e is not None]
    if len(expressoes) != 1:
        raise SQLValidacaoErro("A consulta deve conter exatamente uma única instrução SELECT.")

    arvore = expressoes[0]
    if not isinstance(arvore, exp.Select):
        raise SQLValidacaoErro(
            "Apenas instruções de leitura (SELECT) são permitidas pelo protocolo de segurança."
        )

    # Bloqueia funções de sistema/pragma disfarçadas em FROM
    for func_node in arvore.find_all(exp.Anonymous, exp.Func):
        nome_func = (func_node.sql_name() or "").lower()
        if nome_func.startswith(("pragma_", "sqlite_", "pg_")):
            raise SQLValidacaoErro("Função interna de sistema bloqueada por segurança.")

    nomes_ctes = {
        cte.alias_or_name.lower()
        for cte in arvore.find_all(exp.CTE)
        if cte.alias_or_name
    }

    tabelas_reais: list[str] = []
    for tbl in arvore.find_all(exp.Table):
        if tbl.db or tbl.catalog:
            esquema = (tbl.db or "").lower()
            if esquema and esquema not in ("public", "main"):
                raise SQLValidacaoErro(f"Esquema não autorizado: '{tbl.db}'.")
        nome_tbl = (tbl.name or "").lower()
        if not nome_tbl or nome_tbl in nomes_ctes:
            continue
        if nome_tbl not in TABELAS_PERMITIDAS:
            raise SQLValidacaoErro(
                f"Tabela '{tbl.name}' não autorizada ou inexistente. "
                f"Tabelas permitidas: {', '.join(sorted(TABELAS_PERMITIDAS))}."
            )
        if nome_tbl not in tabelas_reais:
            tabelas_reais.append(nome_tbl)

    if not tabelas_reais and not permitir_select_constante:
        raise SQLValidacaoErro(
            "A consulta deve referenciar ao menos uma tabela corporativa autorizada."
        )

    # Verifica/aplica LIMIT (buscando limite_maximo + 1 linhas para detectar truncamento real)
    teto_busca = limite_maximo + 1
    limit_node = arvore.args.get("limit")
    aplicar_teto = True
    limite_efetivo = limite_maximo
    if isinstance(limit_node, exp.Limit) and limit_node.expression is not None:
        try:
            val_atual = int(limit_node.expression.name)
            if 0 <= val_atual <= limite_maximo:
                aplicar_teto = False
                limite_efetivo = val_atual
        except (ValueError, TypeError, AttributeError):
            aplicar_teto = True

    arvore_final = arvore.limit(teto_busca) if aplicar_teto else arvore
    sql_transpilado = arvore_final.sql(dialect=dialeto_escrita)

    return SQLValidado(
        sql_original_limpo=arvore.sql(dialect=dialeto_escrita),
        sql_com_limite=sql_transpilado,
        tabelas_referenciadas=tuple(tabelas_reais),
        limite_efetivo=limite_efetivo,
    )


def _validar_fallback_stdlib(
    sql_limpo: str,
    mascarado: str,
    limite_maximo: int,
    permitir_select_constante: bool,
) -> SQLValidado:
    """Fallback determinístico quando `sqlglot` não está instalado no ambiente."""
    ctes = {
        m.lower()
        for m in re.findall(r"\bWITH\s+(?:RECURSIVE\s+)?([A-Za-z_][A-Za-z0-9_]*)\s+AS\s*\(", mascarado, flags=re.IGNORECASE)
    }

    # Extrai tabelas após FROM / JOIN (incluindo listas separadas por vírgula no FROM)
    tabelas_reais: list[str] = []
    for bloco_from in re.finditer(
        r"\b(?:FROM|JOIN)\s+([A-Za-z0-9_.,\s]+?)(?=\b(?:WHERE|GROUP|ORDER|HAVING|LIMIT|UNION|JOIN|LEFT|INNER|CROSS|$))",
        mascarado,
        flags=re.IGNORECASE,
    ):
        trecho = bloco_from.group(1).strip()
        if trecho.startswith("("):
            continue
        for parte in trecho.split(","):
            tokens_parte = parte.strip().split()
            if not tokens_parte:
                continue
            bruto_tbl = tokens_parte[0].strip()
            if "(" in bruto_tbl:
                raise SQLValidacaoErro("Funções de tabela no cláusula FROM não são permitidas.")
            if "." in bruto_tbl:
                esquema, nome_tbl = bruto_tbl.rsplit(".", 1)
                if esquema.lower() not in ("public", "main"):
                    raise SQLValidacaoErro(f"Esquema não autorizado: '{esquema}'.")
            else:
                nome_tbl = bruto_tbl
            nl = nome_tbl.lower()
            if nl in ctes:
                continue
            if nl not in TABELAS_PERMITIDAS:
                raise SQLValidacaoErro(
                    f"Tabela '{nome_tbl}' não autorizada ou inexistente. "
                    f"Tabelas permitidas: {', '.join(sorted(TABELAS_PERMITIDAS))}."
                )
            if nl not in tabelas_reais:
                tabelas_reais.append(nl)

    if not tabelas_reais and not permitir_select_constante:
        raise SQLValidacaoErro(
            "A consulta deve referenciar ao menos uma tabela corporativa autorizada."
        )

    teto_busca = limite_maximo + 1
    m_limit = re.search(r"\bLIMIT\s+(\d+)\b", mascarado, flags=re.IGNORECASE)
    if m_limit:
        val_atual = int(m_limit.group(1))
        if val_atual <= limite_maximo:
            return SQLValidado(
                sql_original_limpo=sql_limpo,
                sql_com_limite=sql_limpo,
                tabelas_referenciadas=tuple(tabelas_reais),
                limite_efetivo=val_atual,
            )
        sql_limitado = re.sub(
            r"\bLIMIT\s+\d+\b",
            f"LIMIT {teto_busca}",
            sql_limpo,
            flags=re.IGNORECASE,
        )
    else:
        sql_limitado = f"{sql_limpo} LIMIT {teto_busca}"

    return SQLValidado(
        sql_original_limpo=sql_limpo,
        sql_com_limite=sql_limitado,
        tabelas_referenciadas=tuple(tabelas_reais),
        limite_efetivo=limite_maximo,
    )


def validar_e_preparar_sql(
    sql: str,
    eh_postgres: bool = False,
    limite_maximo: int = LIMITE_LINHAS_CONTEXTO_IA,
    permitir_select_constante: bool = False,
) -> SQLValidado:
    """
    Valida a consulta SQL e devolve sua versão higienizada e limitada.
    Lança `SQLValidacaoErro` com mensagem controlada (sem detalhes internos) em caso de violação.
    """
    sql_limpo = limpar_markdown_sql(sql)
    mascarado = _validar_regras_lexicas_base(sql_limpo)

    dialeto_leitura = "postgres" if eh_postgres else "sqlite"
    dialeto_escrita = "postgres" if eh_postgres else "sqlite"

    try:
        import sqlglot  # noqa: F401

        return _validar_com_sqlglot(
            sql_limpo=sql_limpo,
            dialeto_leitura=dialeto_leitura,
            dialeto_escrita=dialeto_escrita,
            limite_maximo=limite_maximo,
            permitir_select_constante=permitir_select_constante,
        )
    except ImportError:
        return _validar_fallback_stdlib(
            sql_limpo=sql_limpo,
            mascarado=mascarado,
            limite_maximo=limite_maximo,
            permitir_select_constante=permitir_select_constante,
        )
