"""
Pacote de Avaliação de Output do Modelo (LLM Evals) do Jarvis KPI Bot.
Utiliza lazy loading (`__getattr__`) para não exigir `deepeval` ou `ragas` instalados
ao importar guardrails leves como `evals.metricas_jarvis`.
"""
from __future__ import annotations

from typing import Any

__all__ = [
    "CasoAvaliacaoJarvis",
    "JarvisFaithfulnessMetric",
    "JarvisHallucinationMetric",
    "JarvisPersonaTextRulesMetric",
    "avaliar_aderencia_dados",
    "avaliar_output_jarvis",
    "avaliar_reducao_alucinacao",
    "avaliar_regras_texto",
    "construir_golden_dataset",
    "construir_ragas_dataset",
    "consultar_banco_jarvis",
    "executar_comparacao_completa",
    "executar_suite_deepeval",
    "executar_suite_promptfoo",
    "executar_suite_ragas",
    "exportar_golden_dataset_json",
]


def __getattr__(name: str) -> Any:
    if name in (
        "CasoAvaliacaoJarvis",
        "construir_golden_dataset",
        "consultar_banco_jarvis",
        "exportar_golden_dataset_json",
    ):
        from evals import dataset_jarvis

        return getattr(dataset_jarvis, name)

    if name in (
        "avaliar_aderencia_dados",
        "avaliar_output_jarvis",
        "avaliar_reducao_alucinacao",
        "avaliar_regras_texto",
    ):
        from evals import metricas_jarvis

        return getattr(metricas_jarvis, name)

    if name in (
        "JarvisFaithfulnessMetric",
        "JarvisHallucinationMetric",
        "JarvisPersonaTextRulesMetric",
        "executar_suite_deepeval",
    ):
        from evals import eval_deepeval

        return getattr(eval_deepeval, name)

    if name in ("construir_ragas_dataset", "executar_suite_ragas"):
        from evals import eval_ragas

        return getattr(eval_ragas, name)

    if name == "executar_suite_promptfoo":
        from evals.promptfoo_assertions import executar_suite_promptfoo

        return executar_suite_promptfoo

    if name == "executar_comparacao_completa":
        from evals.comparar_ferramentas import executar_comparacao_completa

        return executar_comparacao_completa

    raise AttributeError(f"module 'evals' has no attribute {name!r}")
