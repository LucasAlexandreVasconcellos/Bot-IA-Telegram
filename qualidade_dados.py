"""
Wrapper retrocompatível da camada de qualidade de dados (`jarvis_bot.quality`).
"""
from __future__ import annotations

from jarvis_bot.quality import (
    ANO_MAXIMO,
    ANO_MINIMO,
    CAMPOS_OBRIGATORIOS,
    LIMITE_LINHAS_CONTEXTO_IA,
    METRICAS_COM_NEGATIVO_PERMITIDO,
    TIPOS_PERIODO_VALIDOS,
    VALOR_MAXIMO_PLAUSIVEL,
    ResultadoSanitizacao,
    corrigir_texto,
    sanitizar_linhas_consulta,
    sanitizar_linhas_consulta_detalhada,
    tratar_registro,
    validar_data,
    validar_numero,
    validar_periodo,
)

__all__ = [
    "ANO_MAXIMO",
    "ANO_MINIMO",
    "CAMPOS_OBRIGATORIOS",
    "LIMITE_LINHAS_CONTEXTO_IA",
    "METRICAS_COM_NEGATIVO_PERMITIDO",
    "TIPOS_PERIODO_VALIDOS",
    "VALOR_MAXIMO_PLAUSIVEL",
    "ResultadoSanitizacao",
    "corrigir_texto",
    "sanitizar_linhas_consulta",
    "sanitizar_linhas_consulta_detalhada",
    "tratar_registro",
    "validar_data",
    "validar_numero",
    "validar_periodo",
]
