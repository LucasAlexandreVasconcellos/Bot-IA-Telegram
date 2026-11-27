"""
Avaliação de Output do Jarvis KPI Bot utilizando Ragas (`EvaluationDataset` + `SingleTurnSample`).
Inclui fallback leve compatível caso o pacote opcional `ragas` não esteja instalado no ambiente local/CI.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List

try:
    import ragas as _ragas_pkg
    from ragas.dataset_schema import EvaluationDataset, SingleTurnSample

    _VERSAO_RAGAS = getattr(_ragas_pkg, "__version__", "instalado")
except ImportError:
    _VERSAO_RAGAS = "compat-offline (ragas opcional)"

    @dataclass
    class SingleTurnSample:  # type: ignore[no-redef]
        user_input: str
        retrieved_contexts: List[str] = field(default_factory=list)
        response: str = ""
        reference: str = ""

    @dataclass
    class EvaluationDataset:  # type: ignore[no-redef]
        samples: List[SingleTurnSample] = field(default_factory=list)

from evals.dataset_jarvis import CasoAvaliacaoJarvis, construir_golden_dataset
from evals.metricas_jarvis import (
    avaliar_aderencia_dados,
    avaliar_reducao_alucinacao,
    avaliar_regras_texto,
    julgar_com_llm_ou_local,
    tem_openai_api_key,
)


def construir_ragas_dataset(casos: List[CasoAvaliacaoJarvis] | None = None) -> EvaluationDataset:
    dataset = casos or construir_golden_dataset()
    amostras: List[SingleTurnSample] = [
        SingleTurnSample(
            user_input=c.pergunta,
            retrieved_contexts=c.contexto_recuperado,
            response=c.output_modelo,
            reference=c.resposta_esperada,
        )
        for c in dataset
    ]
    return EvaluationDataset(samples=amostras)


def avaliar_amostra_ragas(
    amostra: SingleTurnSample,
    caso_meta: CasoAvaliacaoJarvis,
    forcar_offline: bool = False,
) -> Dict[str, Any]:
    res_faith_base = avaliar_aderencia_dados(
        output_modelo=amostra.response or "",
        contexto_recuperado=amostra.retrieved_contexts or [],
        valores_obrigatorios=caso_meta.valores_obrigatorios if not caso_meta.exige_ausencia_dados else [],
        valores_proibidos=caso_meta.valores_proibidos,
    )
    res_faith = julgar_com_llm_ou_local(
        criterio="Ragas Faithfulness (Claim-to-Context Grounding)",
        pergunta=amostra.user_input or "",
        output_modelo=amostra.response or "",
        contexto_recuperado=amostra.retrieved_contexts or [],
        resposta_esperada=amostra.reference or "",
        resultado_deterministico=res_faith_base,
        forcar_offline=forcar_offline,
    )

    res_factual_base = avaliar_reducao_alucinacao(
        pergunta=amostra.user_input or "",
        output_modelo=amostra.response or "",
        contexto_recuperado=amostra.retrieved_contexts or [],
        exige_ausencia_dados=caso_meta.exige_ausencia_dados,
        valores_proibidos=caso_meta.valores_proibidos,
    )
    res_factual = julgar_com_llm_ou_local(
        criterio="Ragas FactualCorrectness & Anti-Hallucination",
        pergunta=amostra.user_input or "",
        output_modelo=amostra.response or "",
        contexto_recuperado=amostra.retrieved_contexts or [],
        resposta_esperada=amostra.reference or "",
        resultado_deterministico=res_factual_base,
        forcar_offline=forcar_offline,
    )

    res_aspect_base = avaliar_regras_texto(
        output_modelo=amostra.response or "",
        valores_proibidos_texto=caso_meta.valores_proibidos if caso_meta.categoria == "regras_texto" else [],
    )
    res_aspect = julgar_com_llm_ou_local(
        criterio="Ragas AspectCritic (Persona 'senhor' & No Traceback)",
        pergunta=amostra.user_input or "",
        output_modelo=amostra.response or "",
        contexto_recuperado=amostra.retrieved_contexts or [],
        resposta_esperada=amostra.reference or "",
        resultado_deterministico=res_aspect_base,
        forcar_offline=forcar_offline,
    )

    aprovado_geral = res_faith.aprovado and res_factual.aprovado and res_aspect.aprovado
    return {
        "id": caso_meta.id,
        "ct_referencia": caso_meta.ct_referencia,
        "categoria": caso_meta.categoria,
        "esperado_aprovado": caso_meta.esperado_aprovado,
        "aprovado_obtido": aprovado_geral,
        "detectou_corretamente": aprovado_geral == caso_meta.esperado_aprovado,
        "scores": {
            "aderencia_dados": res_faith.score,
            "reducao_alucinacao": res_factual.score,
            "regras_texto": res_aspect.score,
        },
        "metricas_ragas": {
            "faithfulness": res_faith.score,
            "factual_correctness": res_factual.score,
            "aspect_critic_persona": res_aspect.score,
        },
        "motivos": {
            "aderencia_dados": res_faith.motivo,
            "reducao_alucinacao": res_factual.motivo,
            "regras_texto": res_aspect.motivo,
        },
    }


def executar_suite_ragas(
    casos: List[CasoAvaliacaoJarvis] | None = None,
    forcar_offline: bool = False,
) -> Dict[str, Any]:
    inicio = time.perf_counter()
    dataset_meta = casos or construir_golden_dataset()
    ragas_dataset = construir_ragas_dataset(dataset_meta)

    resultados_casos: List[Dict[str, Any]] = []
    acertos_classificacao = 0

    for amostra, meta in zip(ragas_dataset.samples, dataset_meta):
        res_caso = avaliar_amostra_ragas(amostra, meta, forcar_offline=forcar_offline)
        if res_caso["detectou_corretamente"]:
            acertos_classificacao += 1
        resultados_casos.append(res_caso)

    duracao_ms = round((time.perf_counter() - inicio) * 1000, 2)
    return {
        "ferramenta": "Ragas",
        "versao": _VERSAO_RAGAS,
        "modo": "online_openai" if (tem_openai_api_key() and not forcar_offline) else "offline_hibrido",
        "schema_utilizado": "EvaluationDataset[SingleTurnSample]",
        "total_casos": len(ragas_dataset.samples),
        "acertos_deteccao": acertos_classificacao,
        "acuracia_deteccao": round(acertos_classificacao / max(len(ragas_dataset.samples), 1), 4),
        "tempo_execucao_ms": duracao_ms,
        "casos": resultados_casos,
    }


if __name__ == "__main__":
    relatorio = executar_suite_ragas()
    print(f"=== Ragas ({relatorio['versao']}) ===")
    print(
        f"Casos avaliados: {relatorio['total_casos']} | "
        f"Acurácia de detecção (PASS/FAIL): {relatorio['acuracia_deteccao']*100:.1f}% | "
        f"Tempo: {relatorio['tempo_execucao_ms']} ms"
    )
