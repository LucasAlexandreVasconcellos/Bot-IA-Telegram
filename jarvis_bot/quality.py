"""
Camada defensiva de qualidade de dados do Jarvis KPI Bot.
Validação orientada por esquema/coluna, correção de mojibake, normalização monetária PT-BR,
validação de datas/períodos corporativos, preservação de inteiros e variações negativas legítimas,
deduplicação, truncamento seguro e auditoria em log.
"""
from __future__ import annotations

import logging
import math
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

logger = logging.getLogger("jarvis.qualidade")

METRICAS_COM_NEGATIVO_PERMITIDO = {
    "estorno",
    "ajuste",
    "devolução",
    "devolucao",
    "reembolso",
    "desconto",
    "lucro líquido",
    "lucro liquido",
    "prejuízo",
    "prejuizo",
    "resultado líquido",
    "resultado liquido",
}
TIPOS_PERIODO_VALIDOS = {
    "diario",
    "diário",
    "semanal",
    "mensal",
    "trimestral",
    "semestral",
    "anual",
}
ANO_MINIMO, ANO_MAXIMO = 2000, 2100
VALOR_MAXIMO_PLAUSIVEL = 1e12
CAMPOS_OBRIGATORIOS = ("departamento", "metrica", "tipo_periodo", "periodo")
LIMITE_LINHAS_CONTEXTO_IA = 200

_COLUNAS_INTEIRAS = {"id", "ano"}
_PREFIXOS_INTEIROS = ("qtd_", "contagem_", "count")
_COLUNAS_PERIODO = {"periodo", "mes", "data", "data_referencia"}
_COLUNAS_VARIACAO = {"variacao", "variacao_percentual", "crescimento"}
_COLUNAS_MONETARIAS = {
    "valor",
    "valor_monetario",
    "valor_venda",
    "media",
    "media_venda",
    "total",
    "total_venda",
    "soma",
    "faturamento",
}

_MESES_PT_CANONICO = {
    "janeiro": "Janeiro",
    "jan": "Jan",
    "fevereiro": "Fevereiro",
    "fev": "Fev",
    "março": "Março",
    "marco": "Março",
    "mar": "Mar",
    "abril": "Abril",
    "abr": "Abr",
    "maio": "Maio",
    "mai": "Mai",
    "junho": "Junho",
    "jun": "Jun",
    "julho": "Julho",
    "jul": "Jul",
    "agosto": "Agosto",
    "ago": "Ago",
    "setembro": "Setembro",
    "set": "Set",
    "outubro": "Outubro",
    "out": "Out",
    "novembro": "Novembro",
    "nov": "Nov",
    "dezembro": "Dezembro",
    "dez": "Dez",
}

_MARCADORES_MOJIBAKE = ("Ã", "Â", "â€", "ï»¿")
_CONTROLE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_RE_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_RE_ISO_HORA = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?"
)
_RE_BR = re.compile(r"(\d{2})[/.-](\d{2})[/.-](\d{4})")
_RE_AAAA_BARRA = re.compile(r"(\d{4})/(\d{2})/(\d{2})")

_RE_ANO_PURO = re.compile(r"^(\d{4})$")
_RE_MES_ANO = re.compile(r"^([A-Za-zÀ-ÿ]+)\s*/\s*(\d{4})$")
_RE_SEMANA_MES_ANO = re.compile(
    r"^Semana\s+([1-5])\s*-\s*([A-Za-zÀ-ÿ]+)\s*/\s*(\d{4})$", re.IGNORECASE
)
_RE_TRIMESTRE_SEMESTRE = re.compile(
    r"^(?:([1-4])T|Q([1-4])|([1-2])S)\s*/\s*(\d{4})$", re.IGNORECASE
)


@dataclass
class ResultadoSanitizacao:
    """Resultado completo e auditável da higienização de uma consulta SQL."""

    linhas_limpas: list[dict[str, Any]]
    isolados: int
    truncado: bool = False
    motivos_isolamento: list[str] = field(default_factory=list)


def corrigir_texto(valor: Any) -> tuple[str | None, list[str]]:
    """Decodifica bytes, reverte até 2 camadas de mojibake, remove caracteres de controle e normaliza NFC."""
    problemas: list[str] = []
    if valor is None:
        return None, ["texto_nulo"]

    if isinstance(valor, (bytes, bytearray, memoryview)):
        bruto = bytes(valor)
        try:
            texto = bruto.decode("utf-8")
        except UnicodeDecodeError:
            try:
                texto = bruto.decode("cp1252")
                problemas.append("bytes_decodificados_cp1252")
            except UnicodeDecodeError:
                texto = bruto.decode("utf-8", errors="replace")
                problemas.append("bytes_utf8_invalidos")
    else:
        texto = str(valor)

    for _ in range(2):
        if not any(m in texto for m in _MARCADORES_MOJIBAKE):
            break
        corrigido = None
        for codec in ("latin-1", "cp1252"):
            try:
                corrigido = texto.encode(codec).decode("utf-8")
                break
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
        if corrigido is None or corrigido == texto:
            break
        texto = corrigido
        if "codificacao_corrigida" not in problemas:
            problemas.append("codificacao_corrigida")

    texto = texto.lstrip("\ufeff")
    if _CONTROLE.search(texto):
        texto = _CONTROLE.sub("", texto)
        problemas.append("caracteres_controle_removidos")
    texto = re.sub(r"\s+", " ", unicodedata.normalize("NFC", texto)).strip()

    if "\ufffd" in texto:
        problemas.append("caracteres_substituicao_presentes")
    if not texto:
        return None, problemas + ["texto_vazio"]
    return texto, problemas


def validar_data(valor: Any) -> tuple[str | None, list[str]]:
    """Valida e converte datas calendário (ISO, ISO com hora, DD/MM/AAAA, AAAA/MM/DD) para ISO YYYY-MM-DD."""
    if isinstance(valor, datetime):
        valor = valor.date()
    if isinstance(valor, date):
        if not (ANO_MINIMO <= valor.year <= ANO_MAXIMO):
            return None, ["data_fora_do_intervalo"]
        return valor.isoformat(), []

    if valor is None or str(valor).strip() == "":
        return None, ["data_ausente"]

    texto = str(valor).strip()
    avisos: list[str] = []

    if _RE_ISO.fullmatch(texto):
        ano, mes, dia = map(int, texto.split("-"))
    elif m := _RE_ISO_HORA.fullmatch(texto):
        ano, mes, dia = int(m[1]), int(m[2]), int(m[3])
        avisos.append("data_formato_convertido")
    elif m := _RE_BR.fullmatch(texto):
        dia, mes, ano = int(m[1]), int(m[2]), int(m[3])
        avisos.append("data_formato_convertido")
    elif m := _RE_AAAA_BARRA.fullmatch(texto):
        ano, mes, dia = int(m[1]), int(m[2]), int(m[3])
        avisos.append("data_formato_convertido")
    else:
        return None, ["data_formato_invalido"]

    try:
        data_obj = date(ano, mes, dia)
    except ValueError:
        return None, ["data_invalida"]

    if not (ANO_MINIMO <= data_obj.year <= ANO_MAXIMO):
        return None, ["data_fora_do_intervalo"]
    return data_obj.isoformat(), avisos


def validar_periodo(valor: Any) -> tuple[str | None, list[str]]:
    """
    Valida tanto datas calendário (`validar_data`) quanto períodos corporativos textuais:
    - Anual: `2025`, `2026`
    - Mensal: `Julho/2026`, `Agosto/2026`, `Março/2026`
    - Semanal: `Semana 1 - Ago/2026`
    - Trimestral/Semestral: `1T/2026`, `Q2/2026`, `1S/2026`
    Rejeita datas corrompidas (`2026-15-45`, `0000-00-00`, `2026-04-XX_DATA_CORROMPIDA`, `ontem`, vazios).
    """
    if isinstance(valor, (date, datetime)):
        return validar_data(valor)

    if valor is None:
        return None, ["periodo_ausente"]

    texto_corrigido, erros_txt = corrigir_texto(valor)
    if any(
        e in ("bytes_utf8_invalidos", "caracteres_substituicao_presentes")
        for e in erros_txt
    ):
        return None, erros_txt
    if not texto_corrigido:
        return None, ["periodo_ausente"]

    # 1. Ano puro (ex: "2025")
    if m_ano := _RE_ANO_PURO.fullmatch(texto_corrigido):
        ano = int(m_ano[1])
        if ANO_MINIMO <= ano <= ANO_MAXIMO:
            return str(ano), [e for e in erros_txt if e != "texto_vazio"]
        return None, ["periodo_fora_do_intervalo"]

    # 2. Mês/Ano em português (ex: "Julho/2026")
    if m_mes := _RE_MES_ANO.fullmatch(texto_corrigido):
        nome_mes_raw, ano_str = m_mes[1].casefold(), m_mes[2]
        ano = int(ano_str)
        mes_canon = _MESES_PT_CANONICO.get(nome_mes_raw)
        if mes_canon and (ANO_MINIMO <= ano <= ANO_MAXIMO):
            return f"{mes_canon}/{ano}", erros_txt
        return None, ["periodo_mes_ou_ano_invalido"]

    # 3. Semana N - Mês/Ano (ex: "Semana 4 - Ago/2026")
    if m_sem := _RE_SEMANA_MES_ANO.fullmatch(texto_corrigido):
        num_semana, nome_mes_raw, ano_str = m_sem[1], m_sem[2].casefold(), m_sem[3]
        ano = int(ano_str)
        mes_canon = _MESES_PT_CANONICO.get(nome_mes_raw)
        if mes_canon and (ANO_MINIMO <= ano <= ANO_MAXIMO):
            return f"Semana {num_semana} - {mes_canon}/{ano}", erros_txt
        return None, ["periodo_semanal_invalido"]

    # 4. Trimestre / Semestre (ex: "1T/2026", "Q3/2026", "2S/2026")
    if m_tri := _RE_TRIMESTRE_SEMESTRE.fullmatch(texto_corrigido):
        ano = int(m_tri[4])
        if ANO_MINIMO <= ano <= ANO_MAXIMO:
            prefixo = texto_corrigido.split("/")[0].strip().upper()
            return f"{prefixo}/{ano}", erros_txt
        return None, ["periodo_fora_do_intervalo"]

    # 5. Fallback para data calendário ISO / BR
    data_iso, avisos_data = validar_data(texto_corrigido)
    if data_iso is not None:
        return data_iso, erros_txt + avisos_data
    return None, avisos_data


def _numero_de_texto(texto: str) -> tuple[float | None, bool]:
    s = re.sub(r"^(R\$|\$)\s*", "", texto.strip(), flags=re.IGNORECASE)
    s = re.sub(r"%$", "", s.strip())
    s = re.sub(r"[\s\u00a0]", "", s)
    if not s or "_" in s:
        return None, False
    try:
        return float(s), ("R$" in texto.upper() or "$" in texto or "%" in texto)
    except ValueError:
        pass

    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        if s.count(",") != 1:
            return None, False
        s = s.replace(",", ".")
    elif s.count(".") > 1:
        if not re.fullmatch(r"[+-]?\d{1,3}(\.\d{3})+", s):
            return None, False
        s = s.replace(".", "")

    if not re.fullmatch(r"[+-]?\d+(\.\d+)?([eE][+-]?\d+)?", s):
        return None, False
    try:
        return float(s), True
    except ValueError:
        return None, False


def validar_numero(valor: Any) -> tuple[float | None, list[str]]:
    """Valida e normaliza números (incluindo Decimal e strings monetárias PT-BR/EN), rejeitando bool/NaN/Inf."""
    if valor is None or (isinstance(valor, (str, bytes)) and not valor.strip()):
        return None, ["valor_ausente"]
    if isinstance(valor, bool):
        return None, ["valor_nao_numerico"]

    avisos: list[str] = []
    if isinstance(valor, (int, float, Decimal)):
        numero = float(valor)
    else:
        if isinstance(valor, (bytes, bytearray, memoryview)):
            valor = bytes(valor).decode("utf-8", errors="replace")
        numero, convertido = _numero_de_texto(str(valor))
        if numero is None:
            return None, ["valor_nao_numerico"]
        if convertido:
            avisos.append("valor_formato_convertido")

    if not math.isfinite(numero):
        return None, ["valor_nao_finito"]
    return numero, avisos


def _metrica_permite_valor_negativo(nome_metrica: str | None) -> bool:
    if not nome_metrica:
        return False
    m_norm = nome_metrica.casefold()
    return any(termo in m_norm for termo in METRICAS_COM_NEGATIVO_PERMITIDO)


def _eh_coluna_inteira(col_lower: str) -> bool:
    return col_lower in _COLUNAS_INTEIRAS or col_lower.startswith(_PREFIXOS_INTEIROS)


def _eh_coluna_periodo(col_lower: str) -> bool:
    return col_lower in _COLUNAS_PERIODO


def _eh_coluna_variacao(col_lower: str) -> bool:
    return col_lower in _COLUNAS_VARIACAO or "variacao" in col_lower


def _eh_coluna_monetaria(col_lower: str) -> bool:
    return (
        col_lower in _COLUNAS_MONETARIAS
        or col_lower.startswith(("valor_", "media_", "soma_", "total_"))
    )


def tratar_registro(registro: Mapping[str, Any]) -> dict[str, Any]:
    """Valida um registro estruturado de `indicadores_empresa` com rastreabilidade completa."""
    resultado = dict(registro)
    problemas: list[str] = []

    for campo in ("departamento", "metrica", "tipo_periodo"):
        texto, erros = corrigir_texto(resultado.get(campo))
        resultado[campo] = texto
        problemas.extend(f"{campo}:{e}" for e in erros)

    if resultado.get("tipo_periodo"):
        resultado["tipo_periodo"] = resultado["tipo_periodo"].lower()
        if resultado["tipo_periodo"] not in TIPOS_PERIODO_VALIDOS:
            problemas.append("tipo_periodo:valor_desconhecido")

    periodo, erros = validar_periodo(resultado.get("periodo"))
    resultado["periodo"] = periodo
    problemas.extend(f"periodo:{e}" for e in erros)

    valor, erros = validar_numero(resultado.get("valor_monetario"))
    resultado["valor_monetario"] = valor
    problemas.extend(f"valor_monetario:{e}" for e in erros)

    if "variacao" in resultado:
        variacao, erros_var = validar_numero(resultado.get("variacao"))
        resultado["variacao"] = variacao
        problemas.extend(f"variacao:{e}" for e in erros_var)
    else:
        variacao = 0.0

    bloqueios: list[str] = []
    if any(
        "caracteres_substituicao_presentes" in p or "bytes_utf8_invalidos" in p
        for p in problemas
    ):
        bloqueios.append("texto_irrecuperavel")
    if "tipo_periodo:valor_desconhecido" in problemas:
        bloqueios.append("tipo_periodo_invalido")
    if "variacao" in resultado and variacao is None:
        bloqueios.append("variacao_invalida")
    elif variacao is not None and abs(variacao) > VALOR_MAXIMO_PLAUSIVEL:
        problemas.append("variacao:fora_do_intervalo_plausivel")
        bloqueios.append("variacao_fora_do_intervalo")

    if valor is not None:
        if abs(valor) > VALOR_MAXIMO_PLAUSIVEL:
            problemas.append("valor_monetario:fora_do_intervalo_plausivel")
            bloqueios.append("valor_fora_do_intervalo")
        elif valor < 0:
            if _metrica_permite_valor_negativo(resultado.get("metrica")):
                problemas.append("valor_monetario:negativo_permitido_pela_metrica")
            else:
                problemas.append("valor_monetario:negativo_anomalo")
                bloqueios.append("valor_negativo")

    faltantes = [c for c in CAMPOS_OBRIGATORIOS if not resultado.get(c)]
    if faltantes:
        problemas.append("campos_obrigatorios_ausentes:" + ",".join(faltantes))

    resultado["problemas_qualidade"] = problemas
    resultado["utilizavel"] = not faltantes and not bloqueios and valor is not None
    return resultado


def sanitizar_linhas_consulta_detalhada(
    linhas: list[dict[str, Any]],
    limite: int = LIMITE_LINHAS_CONTEXTO_IA,
) -> ResultadoSanitizacao:
    """
    Higieniza registros arbitrários vindos de consultas SQL aplicando regras específicas por coluna:
    - Preserva variações percentuais negativas legítimas (DEF-001: CAC, Churn, Semana 4).
    - Valida strings monetárias/numéricas e rejeita NULL/textos inválidos em colunas numéricas (DEF-002).
    - Valida datas e períodos corporativos textuais e deduplica registros (DEF-003).
    - Preserva inteiros como `int` (DEF-012) e registra motivos de isolamento no logger.
    - Aplica `LIMITE_LINHAS_CONTEXTO_IA` sinalizando truncamento (DEF-007).
    """
    limpos: list[dict[str, Any]] = []
    isolados = 0
    motivos_isolamento: list[str] = []
    vistos: set[tuple[tuple[str, Any], ...]] = set()

    for idx, r in enumerate(linhas):
        item: dict[str, Any] = {}
        motivo_falha: str | None = None

        # Pré-extrai métrica higienizada (se existir na linha) para avaliar regra de negativo
        metrica_bruta = r.get("metrica")
        metrica_limpa, _ = (
            corrigir_texto(metrica_bruta) if metrica_bruta is not None else (None, [])
        )

        for k, v in r.items():
            col_lower = str(k).strip().lower()

            # 1. Colunas inteiras (id, ano, contagens)
            if _eh_coluna_inteira(col_lower):
                if isinstance(v, bool) or v is None:
                    motivo_falha = f"{k}:inteiro_invalido_ou_nulo"
                    break
                if isinstance(v, int):
                    num_int = v
                else:
                    num_f, _ = validar_numero(v)
                    if num_f is None or not float(num_f).is_integer():
                        motivo_falha = f"{k}:valor_nao_inteiro"
                        break
                    num_int = int(num_f)
                if col_lower == "ano" and not (ANO_MINIMO <= num_int <= ANO_MAXIMO):
                    motivo_falha = f"{k}:ano_fora_do_intervalo({num_int})"
                    break
                item[k] = num_int

            # 2. Colunas de período / data
            elif _eh_coluna_periodo(col_lower):
                per_limpo, erros_per = validar_periodo(v)
                if per_limpo is None:
                    motivo_falha = f"{k}:{','.join(erros_per) or 'periodo_invalido'}"
                    break
                item[k] = per_limpo

            # 3. Colunas de variação percentual (negativos são legítimos!)
            elif _eh_coluna_variacao(col_lower):
                num_var, erros_var = validar_numero(v)
                if num_var is None:
                    motivo_falha = f"{k}:{','.join(erros_var) or 'variacao_invalida'}"
                    break
                if abs(num_var) > VALOR_MAXIMO_PLAUSIVEL:
                    motivo_falha = f"{k}:fora_do_intervalo_plausivel"
                    break
                item[k] = num_var

            # 4. Colunas monetárias / métricas numéricas conhecidas
            elif _eh_coluna_monetaria(col_lower):
                num_val, erros_val = validar_numero(v)
                if num_val is None:
                    motivo_falha = f"{k}:{','.join(erros_val) or 'valor_invalido'}"
                    break
                if abs(num_val) > VALOR_MAXIMO_PLAUSIVEL:
                    motivo_falha = f"{k}:fora_do_intervalo_plausivel"
                    break
                if num_val < 0:
                    if _metrica_permite_valor_negativo(metrica_limpa):
                        logger.info(
                            "Linha %d: valor negativo %.2f preservado pela regra da métrica %r",
                            idx,
                            num_val,
                            metrica_limpa,
                        )
                    else:
                        motivo_falha = f"{k}:valor_negativo_anomalo({num_val})"
                        break
                item[k] = num_val

            # 5. Valores já numéricos em colunas genéricas/calculadas (ex: AVG/SUM sem alias padrão)
            elif isinstance(v, (int, float, Decimal)) and not isinstance(v, bool):
                if isinstance(v, int):
                    num_gen: int | float = v
                else:
                    num_f, erros_f = validar_numero(v)
                    if num_f is None:
                        motivo_falha = f"{k}:{','.join(erros_f) or 'numero_invalido'}"
                        break
                    num_gen = num_f
                if abs(float(num_gen)) > VALOR_MAXIMO_PLAUSIVEL:
                    motivo_falha = f"{k}:fora_do_intervalo_plausivel"
                    break
                if float(num_gen) < 0 and not _metrica_permite_valor_negativo(metrica_limpa):
                    motivo_falha = f"{k}:numero_negativo_anomalo({num_gen})"
                    break
                item[k] = num_gen

            # 6. Colunas textuais (departamento, metrica, tipo_periodo, loja, linha_produto, etc.)
            elif isinstance(v, (str, bytes, bytearray, memoryview)):
                texto_limpo, erros_txt = corrigir_texto(v)
                if texto_limpo is None or any(
                    e in ("bytes_utf8_invalidos", "caracteres_substituicao_presentes")
                    for e in erros_txt
                ):
                    motivo_falha = f"{k}:{','.join(erros_txt) or 'texto_invalido'}"
                    break
                if col_lower == "tipo_periodo" and texto_limpo.lower() not in TIPOS_PERIODO_VALIDOS:
                    motivo_falha = f"{k}:tipo_periodo_desconhecido({texto_limpo})"
                    break
                item[k] = texto_limpo

            # 7. Nulos ou booleanos em colunas obrigatórias/desconhecidas
            elif v is None or isinstance(v, bool):
                motivo_falha = f"{k}:campo_nulo_ou_booleano"
                break

            else:
                item[k] = v

        if motivo_falha is not None:
            isolados += 1
            motivos_isolamento.append(f"linha_{idx}:{motivo_falha}")
            logger.warning("Registro isolado na qualidade (linha %d): %s", idx, motivo_falha)
            continue

        # Deduplicação apenas quando a linha contém a chave completa de negócio da entidade
        cols_presentes = {ck.lower() for ck in item.keys()}
        tem_chave_entidade = (
            {"departamento", "metrica", "tipo_periodo", "periodo"}.issubset(cols_presentes)
            or {"loja", "linha_produto", "ano", "mes"}.issubset(cols_presentes)
        )
        if tem_chave_entidade:
            chaves_negocio = tuple(
                (ck, cv) for ck, cv in sorted(item.items()) if ck.lower() != "id"
            )
            if chaves_negocio in vistos:
                isolados += 1
                motivos_isolamento.append(f"linha_{idx}:registro_duplicado")
                logger.warning("Registro duplicado isolado na qualidade (linha %d)", idx)
                continue
            vistos.add(chaves_negocio)
        limpos.append(item)

    truncado = len(limpos) > limite
    if truncado:
        limpos = limpos[:limite]

    return ResultadoSanitizacao(
        linhas_limpas=limpos,
        isolados=isolados,
        truncado=truncado,
        motivos_isolamento=motivos_isolamento,
    )


def sanitizar_linhas_consulta(
    linhas: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Assinatura retrocompatível `(linhas_limpas, qtd_isolados)`."""
    res = sanitizar_linhas_consulta_detalhada(linhas)
    return res.linhas_limpas, res.isolados
