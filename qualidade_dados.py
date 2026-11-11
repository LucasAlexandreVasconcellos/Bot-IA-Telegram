"""
Camada defensiva de qualidade de dados do Jarvis.
Python 3.10+ | SQLite / Postgres | sem dependências externas.
"""
from __future__ import annotations

import logging
import math
import re
import unicodedata
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

logger = logging.getLogger("jarvis.qualidade")

METRICAS_COM_NEGATIVO_PERMITIDO = {
    "estorno", "ajuste", "devolução", "devolucao", "reembolso", "desconto",
}
TIPOS_PERIODO_VALIDOS = {
    "diario", "diário", "semanal", "mensal", "trimestral", "semestral", "anual"
}
ANO_MINIMO, ANO_MAXIMO = 2000, 2100
VALOR_MAXIMO_PLAUSIVEL = 1e12
CAMPOS_OBRIGATORIOS = ("departamento", "metrica", "tipo_periodo", "periodo")
LIMITE_LINHAS_CONTEXTO_IA = 200

_MARCADORES_MOJIBAKE = ("Ã", "Â", "â€", "ï»¿")
_CONTROLE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def corrigir_texto(valor: Any) -> tuple[str | None, list[str]]:
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


_RE_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_RE_ISO_HORA = re.compile(r"(\d{4})-(\d{2})-(\d{2})[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?")
_RE_BR = re.compile(r"(\d{2})[/.-](\d{2})[/.-](\d{4})")
_RE_AAAA_BARRA = re.compile(r"(\d{4})/(\d{2})/(\d{2})")


def validar_data(valor: Any) -> tuple[str | None, list[str]]:
    if isinstance(valor, datetime):
        valor = valor.date()
    if isinstance(valor, date):
        valor = valor.isoformat()

    if valor is None or str(valor).strip() == "":
        return None, ["data_ausente"]

    texto = str(valor).strip()
    avisos: list[str] = []

    if _RE_ISO.fullmatch(texto):
        ano, mes, dia = map(int, texto.split("-"))
    elif (m := _RE_ISO_HORA.fullmatch(texto)):
        ano, mes, dia = int(m[1]), int(m[2]), int(m[3])
        avisos.append("data_formato_convertido")
    elif (m := _RE_BR.fullmatch(texto)):
        dia, mes, ano = int(m[1]), int(m[2]), int(m[3])
        avisos.append("data_formato_convertido")
    elif (m := _RE_AAAA_BARRA.fullmatch(texto)):
        ano, mes, dia = int(m[1]), int(m[2]), int(m[3])
        avisos.append("data_formato_convertido")
    else:
        return None, ["data_formato_invalido"]

    try:
        data = date(ano, mes, dia)
    except ValueError:
        return None, ["data_invalida"]

    if not (ANO_MINIMO <= data.year <= ANO_MAXIMO):
        return None, ["data_fora_do_intervalo"]
    return data.isoformat(), avisos


def _numero_de_texto(texto: str) -> tuple[float | None, bool]:
    s = re.sub(r"^(R\$|\$)\s*", "", texto.strip(), flags=re.IGNORECASE)
    s = re.sub(r"[\s\u00a0]", "", s)
    if not s or "_" in s:
        return None, False
    try:
        return float(s), False
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

    if not re.fullmatch(r"[+-]?\d+(\.\d+)?", s):
        return None, False
    return float(s), True


def validar_numero(valor: Any) -> tuple[float | None, list[str]]:
    if valor is None or (isinstance(valor, (str, bytes)) and not valor.strip()):
        return None, ["valor_ausente"]
    if isinstance(valor, bool):
        return None, ["valor_nao_numerico"]

    avisos: list[str] = []
    if isinstance(valor, (int, float)):
        numero = float(valor)
    else:
        if isinstance(valor, (bytes, bytearray)):
            valor = bytes(valor).decode("utf-8", errors="replace")
        numero, convertido = _numero_de_texto(str(valor))
        if numero is None:
            return None, ["valor_nao_numerico"]
        if convertido:
            avisos.append("valor_formato_convertido")

    if not math.isfinite(numero):
        return None, ["valor_nao_finito"]
    return numero, avisos


def tratar_registro(registro: Mapping[str, Any]) -> dict[str, Any]:
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

    periodo_bruto = resultado.get("periodo")
    if isinstance(periodo_bruto, (bytes, bytearray)):
        periodo_bruto, _ = corrigir_texto(periodo_bruto)
    periodo, erros = validar_data(periodo_bruto)
    resultado["periodo"] = periodo
    problemas.extend(f"periodo:{e}" for e in erros)

    valor, erros = validar_numero(resultado.get("valor_monetario"))
    resultado["valor_monetario"] = valor
    problemas.extend(f"valor_monetario:{e}" for e in erros)

    variacao, erros = validar_numero(resultado.get("variacao"))
    resultado["variacao"] = variacao
    problemas.extend(f"variacao:{e}" for e in erros)

    bloqueios: list[str] = []
    if any("caracteres_substituicao_presentes" in p or "bytes_utf8_invalidos" in p for p in problemas):
        bloqueios.append("texto_irrecuperavel")
    if valor is not None:
        if abs(valor) > VALOR_MAXIMO_PLAUSIVEL:
            problemas.append("valor_monetario:fora_do_intervalo_plausivel")
            bloqueios.append("valor_fora_do_intervalo")
        elif valor < 0:
            metrica = (resultado.get("metrica") or "").casefold()
            if metrica in METRICAS_COM_NEGATIVO_PERMITIDO:
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


def sanitizar_linhas_consulta(linhas: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    limpos = []
    isolados = 0

    for r in linhas:
        item = {}
        invalido = False

        for k, v in r.items():
            if isinstance(v, (str, bytes)):
                texto_limpo, erros = corrigir_texto(v)
                if any("bytes_utf8_invalidos" in e or "caracteres_substituicao_presentes" in e for e in erros):
                    invalido = True
                    break
                item[k] = texto_limpo
            elif isinstance(v, (int, float)):
                num_limpo, erros = validar_numero(v)
                if num_limpo is None or abs(num_limpo) > VALOR_MAXIMO_PLAUSIVEL:
                    invalido = True
                    break
                if num_limpo < 0 and "estorno" not in str(r.get("metrica", "")).lower() and "devolucao" not in str(r.get("metrica", "")).lower():
                    invalido = True
                    break
                item[k] = num_limpo
            else:
                item[k] = v

        if invalido:
            isolados += 1
        else:
            limpos.append(item)

    return limpos, isolados
