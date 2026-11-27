"""
Modelos Pydantic 2.0 com validação estrita de consistência, segurança SQL e regras de persona
(CT-027 / CT-031 / DEF-008 / DEF-009 / PEND-01).
"""
from __future__ import annotations

import math
import re
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from jarvis_bot.sql_guard import SQLValidacaoErro, limpar_markdown_sql, validar_e_preparar_sql

_RE_TERMINA_SENHOR = re.compile(r"\bsenhor[.!?\"')\]\s]*$", re.IGNORECASE)

_PADROES_PROIBIDOS_RESPOSTA = (
    "traceback (most recent call last)",
    "/tmp/jarvis_sandbox",
    "jarvis_sandbox_",
    "sqlite3.operationalerror",
    "psycopg2.",
    "sandboxsecurityerror",
    "script_ia.py",
)


class RoteamentoConsulta(BaseModel):
    """Classificação estruturada da intenção do usuário e query SQL segura."""

    tipo_solicitacao: Literal["banco_dados", "geral_ou_externo"] = Field(
        ...,
        description=(
            "Use 'banco_dados' se a pergunta envolver indicadores da empresa, faturamento, "
            "EBITDA, lucro, CAC, churn, ROI, lojas ou vendas internas (mesmo para períodos "
            "futuros ou ausentes como 2024, Setembro/2026 ou 2027). Use 'geral_ou_externo' "
            "para saudações, hora, conceitos teóricos, cálculos gerais ou temas externos (PIB, inflação global)."
        ),
    )
    sql_query: str = Field(
        ...,
        description=(
            "Comando SQL SELECT válido sobre 'indicadores_empresa' ou 'vendas_lojas' caso "
            "tipo_solicitacao seja 'banco_dados'. Caso seja 'geral_ou_externo', retorne 'SELECT 1'."
        ),
    )

    @model_validator(mode="after")
    def _validar_roteamento_sql(self) -> "RoteamentoConsulta":
        sql_limpo = limpar_markdown_sql(self.sql_query)
        if not sql_limpo:
            raise ValueError("sql_query não pode ser vazia.")

        if self.tipo_solicitacao == "banco_dados":
            try:
                validado = validar_e_preparar_sql(
                    sql_limpo, permitir_select_constante=False
                )
            except SQLValidacaoErro as exc:
                raise ValueError(f"Consulta SQL inválida para banco_dados: {exc}") from exc
            self.sql_query = validado.sql_original_limpo
        else:
            # Mesmo em geral_ou_externo, rejeita qualquer instrução destrutiva/não-SELECT
            try:
                validar_e_preparar_sql(sql_limpo, permitir_select_constante=True)
            except SQLValidacaoErro as exc:
                raise ValueError(f"sql_query insegura em geral_ou_externo: {exc}") from exc
            self.sql_query = sql_limpo
        return self


class EstruturaGrafico(BaseModel):
    """Especificação validada para renderização de gráficos de barras, linhas ou pizza."""

    tipo: Literal["barra", "linha", "pizza"] = Field(
        ..., description="Tipo do gráfico: barra, linha ou pizza."
    )
    titulo: str = Field(..., min_length=3, description="Título descritivo do gráfico.")
    rotulos_x: List[str] = Field(
        ..., description="Lista não vazia de rótulos para categorias, períodos ou fatias."
    )
    valores_y: List[float] = Field(
        ..., description="Lista não vazia de valores numéricos positivos correspondentes."
    )
    label_eixo_x: Optional[str] = Field(None, description="Nome do eixo X.")
    label_eixo_y: Optional[str] = Field(None, description="Nome do eixo Y.")

    @model_validator(mode="after")
    def _validar_consistencia_grafico(self) -> "EstruturaGrafico":
        self.titulo = self.titulo.strip()
        if not self.titulo:
            raise ValueError("O título do gráfico não pode ser vazio.")

        if not self.rotulos_x or not self.valores_y:
            raise ValueError("rotulos_x e valores_y devem conter ao menos um elemento.")

        if len(self.rotulos_x) != len(self.valores_y):
            raise ValueError(
                f"Inconsistência de dimensões: {len(self.rotulos_x)} rótulos para "
                f"{len(self.valores_y)} valores."
            )

        rotulos_limpos: list[str] = []
        for r in self.rotulos_x:
            texto_r = str(r).strip()
            if not texto_r:
                raise ValueError("Rótulos do gráfico não podem ser vazios.")
            rotulos_limpos.append(texto_r)
        self.rotulos_x = rotulos_limpos

        for v in self.valores_y:
            if isinstance(v, bool) or not math.isfinite(v):
                raise ValueError("Todos os valores do gráfico devem ser números finitos.")
            if v < 0:
                raise ValueError("Valores negativos não são permitidos em valores_y do gráfico.")

        if self.tipo == "pizza":
            if any(v <= 0 for v in self.valores_y) or sum(self.valores_y) <= 0:
                raise ValueError(
                    "Gráficos de pizza exigem valores estritamente positivos em todas as fatias."
                )

        return self


class RespostaAgente(BaseModel):
    """Resposta final validada do Jarvis seguindo as regras de persona e segurança."""

    texto_resposta: str = Field(
        ...,
        min_length=5,
        description=(
            "Resposta executiva completa, direta e elegante em tom Jarvis, "
            "finalizada obrigatoriamente com a palavra 'senhor'."
        ),
    )
    gerar_grafico: bool = Field(
        ...,
        description="True apenas quando houver solicitação visual E dados válidos suficientes.",
    )
    grafico: Optional[EstruturaGrafico] = Field(
        None,
        description="Dados estruturados do gráfico quando gerar_grafico for True; None caso contrário.",
    )

    @model_validator(mode="after")
    def _validar_regras_resposta(self) -> "RespostaAgente":
        texto = (self.texto_resposta or "").strip()
        if not texto:
            raise ValueError("texto_resposta não pode ser vazio.")

        texto_lower = texto.lower()
        for padrao in _PADROES_PROIBIDOS_RESPOSTA:
            if padrao in texto_lower:
                raise ValueError(f"Exposição de detalhe técnico interno bloqueada: '{padrao}'.")

        if not _RE_TERMINA_SENHOR.search(texto):
            raise ValueError(
                "A resposta deve terminar obrigatoriamente com a palavra 'senhor'."
            )

        if self.gerar_grafico and self.grafico is None:
            raise ValueError("O objeto 'grafico' é obrigatório quando gerar_grafico=True.")

        if not self.gerar_grafico and self.grafico is not None:
            self.grafico = None

        self.texto_resposta = texto
        return self
