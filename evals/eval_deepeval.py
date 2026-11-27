"""
Avaliação de Output do Jarvis KPI Bot utilizando DeepEval (`LLMTestCase` + `BaseMetric`).
Inclui fallback leve compatível caso o pacote opcional `deepeval` não esteja instalado no ambiente local/CI,
permitindo que a suíte de testes unitários execute sem dependências pesadas externas.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List

try:
    import deepeval as _deepeval_pkg
    from deepeval.metrics import BaseMetric
    from deepeval.test_case import LLMTestCase

    _VERSAO_DEEPEVAL = getattr(_deepeval_pkg, "__version__", "instalado")
except ImportError:
    _VERSAO_DEEPEVAL = "compat-offline (deepeval opcional)"

    class BaseMetric:  # type: ignore[no-redef]
        threshold: float = 0.8
        score: float = 0.0
        reason: str = ""
        success: bool = False

    @dataclass
    class LLMTestCase:  # type: ignore[no-redef]
        input: str
        actual_output: str
        expected_output: str = ""
        retrieval_context: List[str] = field(default_factory=list)
        context: List[str] = field(default_factory=list)
        additional_metadata: Dict[str, Any] = field(default_factory=dict)

from evals.dataset_jarvis import CasoAvaliacaoJarvis, construir_golden_dataset
from evals.metricas_jarvis import (
    avaliar_aderencia_dados,
    avaliar_reducao_alucinacao,
    avaliar_regras_texto,
    julgar_com_llm_ou_local,
    tem_openai_api_key,
)


class JarvisFaithfulnessMetric(BaseMetric):
    """Métrica DeepEval para avaliar aderência estrita aos dados do banco (Faithfulness)."""

    def __init__(
        self,
        valores_obrigatorios: List[str] | None = None,
        valores_proibidos: List[str] | None = None,
        threshold: float = 0.8,
        forcar_offline: bool = False,
    ):
        self.threshold = threshold
        self.valores_obrigatorios = valores_obrigatorios or []
        self.valores_proibidos = valores_proibidos or []
        self.forcar_offline = forcar_offline
        self.score = 0.0
        self.reason = ""
        self.success = False
        self.evaluation_model = (
            "gpt-4o-mini (Híbrido)"
            if (tem_openai_api_key() and not forcar_offline)
            else "JarvisContextualJudge (Offline)"
        )

    def measure(self, test_case: LLMTestCase, *args: Any, **kwargs: Any) -> float:
        res_base = avaliar_aderencia_dados(
            output_modelo=test_case.actual_output or "",
            contexto_recuperado=test_case.retrieval_context or [],
            valores_obrigatorios=self.valores_obrigatorios,
            valores_proibidos=self.valores_proibidos,
            threshold=self.threshold,
        )
        res = julgar_com_llm_ou_local(
            criterio="Aderência aos Dados (Faithfulness)",
            pergunta=test_case.input or "",
            output_modelo=test_case.actual_output or "",
            contexto_recuperado=test_case.retrieval_context or [],
            resposta_esperada=test_case.expected_output or "",
            resultado_deterministico=res_base,
            forcar_offline=self.forcar_offline,
        )
        self.score = res.score
        self.reason = res.motivo
        self.success = res.aprovado
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args: Any, **kwargs: Any) -> float:
        return self.measure(test_case, *args, **kwargs)

    def is_successful(self) -> bool:
        return bool(self.success)

    @property
    def __name__(self) -> str:
        return "Jarvis Faithfulness (DeepEval)"


class JarvisHallucinationMetric(BaseMetric):
    """Métrica DeepEval para detecção e prevenção de alucinações (incluindo fallback DEF-015)."""

    def __init__(
        self,
        exige_ausencia_dados: bool = False,
        valores_proibidos: List[str] | None = None,
        threshold: float = 0.8,
        forcar_offline: bool = False,
    ):
        self.threshold = threshold
        self.exige_ausencia_dados = exige_ausencia_dados
        self.valores_proibidos = valores_proibidos or []
        self.forcar_offline = forcar_offline
        self.score = 0.0
        self.reason = ""
        self.success = False
        self.evaluation_model = (
            "gpt-4o-mini (Híbrido)"
            if (tem_openai_api_key() and not forcar_offline)
            else "JarvisContextualJudge (Offline)"
        )

    def measure(self, test_case: LLMTestCase, *args: Any, **kwargs: Any) -> float:
        res_base = avaliar_reducao_alucinacao(
            pergunta=test_case.input or "",
            output_modelo=test_case.actual_output or "",
            contexto_recuperado=test_case.context or test_case.retrieval_context or [],
            exige_ausencia_dados=self.exige_ausencia_dados,
            valores_proibidos=self.valores_proibidos,
            threshold=self.threshold,
        )
        res = julgar_com_llm_ou_local(
            criterio="Redução de Alucinações (Anti-Hallucination & Fallback DEF-015)",
            pergunta=test_case.input or "",
            output_modelo=test_case.actual_output or "",
            contexto_recuperado=test_case.context or test_case.retrieval_context or [],
            resposta_esperada=test_case.expected_output or "",
            resultado_deterministico=res_base,
            forcar_offline=self.forcar_offline,
        )
        self.score = res.score
        self.reason = res.motivo
        self.success = res.aprovado
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args: Any, **kwargs: Any) -> float:
        return self.measure(test_case, *args, **kwargs)

    def is_successful(self) -> bool:
        return bool(self.success)

    @property
    def __name__(self) -> str:
        return "Jarvis Anti-Hallucination (DeepEval)"


class JarvisPersonaTextRulesMetric(BaseMetric):
    """Métrica DeepEval para regras de texto e persona ('senhor')."""

    def __init__(
        self,
        valores_proibidos: List[str] | None = None,
        threshold: float = 0.9,
        forcar_offline: bool = False,
    ):
        self.threshold = threshold
        self.valores_proibidos = valores_proibidos or []
        self.forcar_offline = forcar_offline
        self.score = 0.0
        self.reason = ""
        self.success = False
        self.evaluation_model = (
            "gpt-4o-mini (Híbrido)"
            if (tem_openai_api_key() and not forcar_offline)
            else "JarvisContextualJudge (Offline)"
        )

    def measure(self, test_case: LLMTestCase, *args: Any, **kwargs: Any) -> float:
        res_base = avaliar_regras_texto(
            output_modelo=test_case.actual_output or "",
            valores_proibidos_texto=self.valores_proibidos,
            threshold=self.threshold,
        )
        res = julgar_com_llm_ou_local(
            criterio="Cumprimento das Regras de Resposta em Texto e Persona ('senhor')",
            pergunta=test_case.input or "",
            output_modelo=test_case.actual_output or "",
            contexto_recuperado=test_case.retrieval_context or [],
            resposta_esperada=test_case.expected_output or "",
            resultado_deterministico=res_base,
            forcar_offline=self.forcar_offline,
        )
        self.score = res.score
        self.reason = res.motivo
        self.success = res.aprovado
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args: Any, **kwargs: Any) -> float:
        return self.measure(test_case, *args, **kwargs)

    def is_successful(self) -> bool:
        return bool(self.success)

    @property
    def __name__(self) -> str:
        return "Jarvis Text & Persona Rules (DeepEval)"


def converter_para_deepeval_testcase(caso: CasoAvaliacaoJarvis) -> LLMTestCase:
    return LLMTestCase(
        input=caso.pergunta,
        actual_output=caso.output_modelo,
        expected_output=caso.resposta_esperada,
        retrieval_context=caso.contexto_recuperado,
        context=caso.contexto_recuperado,
        additional_metadata={
            "id": caso.id,
            "ct_referencia": caso.ct_referencia,
            "categoria": caso.categoria,
            "sql_executado": caso.sql_executado,
        },
    )


def executar_suite_deepeval(
    casos: List[CasoAvaliacaoJarvis] | None = None,
    forcar_offline: bool = False,
) -> Dict[str, Any]:
    inicio = time.perf_counter()
    dataset = casos or construir_golden_dataset()
    resultados_casos: List[Dict[str, Any]] = []
    acertos_classificacao = 0

    for caso in dataset:
        tc = converter_para_deepeval_testcase(caso)
        m_faith = JarvisFaithfulnessMetric(
            valores_obrigatorios=caso.valores_obrigatorios if not caso.exige_ausencia_dados else [],
            valores_proibidos=caso.valores_proibidos,
            forcar_offline=forcar_offline,
        )
        m_halluc = JarvisHallucinationMetric(
            exige_ausencia_dados=caso.exige_ausencia_dados,
            valores_proibidos=caso.valores_proibidos,
            forcar_offline=forcar_offline,
        )
        m_rules = JarvisPersonaTextRulesMetric(
            valores_proibidos=caso.valores_proibidos if caso.categoria == "regras_texto" else [],
            forcar_offline=forcar_offline,
        )

        for metrica in (m_faith, m_halluc, m_rules):
            metrica.measure(tc)

        aprovado_geral = m_faith.is_successful() and m_halluc.is_successful() and m_rules.is_successful()
        classificacao_correta = aprovado_geral == caso.esperado_aprovado
        if classificacao_correta:
            acertos_classificacao += 1

        resultados_casos.append(
            {
                "id": caso.id,
                "ct_referencia": caso.ct_referencia,
                "categoria": caso.categoria,
                "esperado_aprovado": caso.esperado_aprovado,
                "aprovado_obtido": aprovado_geral,
                "detectou_corretamente": classificacao_correta,
                "scores": {
                    "aderencia_dados": m_faith.score,
                    "reducao_alucinacao": m_halluc.score,
                    "regras_texto": m_rules.score,
                },
                "motivos": {
                    "aderencia_dados": m_faith.reason,
                    "reducao_alucinacao": m_halluc.reason,
                    "regras_texto": m_rules.reason,
                },
            }
        )

    duracao_ms = round((time.perf_counter() - inicio) * 1000, 2)
    return {
        "ferramenta": "DeepEval",
        "versao": _VERSAO_DEEPEVAL,
        "modo": "online_openai" if (tem_openai_api_key() and not forcar_offline) else "offline_hibrido",
        "total_casos": len(dataset),
        "acertos_deteccao": acertos_classificacao,
        "acuracia_deteccao": round(acertos_classificacao / max(len(dataset), 1), 4),
        "tempo_execucao_ms": duracao_ms,
        "casos": resultados_casos,
    }


if __name__ == "__main__":
    relatorio = executar_suite_deepeval()
    print(f"=== DeepEval ({relatorio['modo']}) ===")
    print(
        f"Casos avaliados: {relatorio['total_casos']} | "
        f"Acurácia de detecção (PASS/FAIL): {relatorio['acuracia_deteccao']*100:.1f}% | "
        f"Tempo: {relatorio['tempo_execucao_ms']} ms"
    )
