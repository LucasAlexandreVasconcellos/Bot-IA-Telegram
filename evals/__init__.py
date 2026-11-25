"""
Pacote de Avaliação de Output do Modelo (LLM Evals) do Jarvis KPI Bot.

Cobre os três pilares de avaliação:
1. Aderência aos dados (Faithfulness / Factual Correctness)
2. Redução de alucinações (Hallucination Detection & Fallback Trap Prevention)
3. Cumprimento das regras de resposta em texto (Persona 'senhor', Tom Executivo, Sem Tracebacks)

Ferramentas implementadas e comparadas:
- DeepEval (`evals.eval_deepeval`)
- Ragas (`evals.eval_ragas`)
- Promptfoo (`evals.promptfooconfig.yaml` / `evals.promptfoo_assertions`)
"""
from evals.comparar_ferramentas import executar_comparacao_completa
from evals.dataset_jarvis import (
    CasoAvaliacaoJarvis,
    construir_golden_dataset,
    consultar_banco_jarvis,
    exportar_golden_dataset_json,
)
from evals.eval_deepeval import (
    JarvisFaithfulnessMetric,
    JarvisHallucinationMetric,
    JarvisPersonaTextRulesMetric,
    executar_suite_deepeval,
)
from evals.eval_ragas import construir_ragas_dataset, executar_suite_ragas
from evals.metricas_jarvis import (
    avaliar_aderencia_dados,
    avaliar_output_jarvis,
    avaliar_reducao_alucinacao,
    avaliar_regras_texto,
)
from evals.promptfoo_assertions import executar_suite_promptfoo

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
