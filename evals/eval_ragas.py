"""
Avaliação de Output do Jarvis KPI Bot utilizando a biblioteca Ragas (`ragas==0.4.4`).

Demonstra:
- Estruturação do dataset no esquema oficial do Ragas (`SingleTurnSample` e `EvaluationDataset`)
  mapeando:
  * `user_input` <- pergunta do usuário no Telegram
  * `retrieved_contexts` <- JSON retornado pelo SQLite `sandbox_jarvis.db` após `sanitizar_linhas_consulta`
  * `response` <- `texto_resposta` gerado pelo Jarvis
  * `reference` <- resposta executiva esperada (Ground Truth)
- Avaliação das métricas orientadas a RAG/Contexto:
  1. `faithfulness` (Aderência das afirmações ao `retrieved_contexts`)
  2. `factual_correctness` / `anti_hallucination` (Correspondência factual com `reference` e detecção de alucinação no fallback DEF-015)
  3. `aspect_critic_jarvis_persona` (Crítico de aspecto para regras de texto: sufixo 'senhor', anti-traceback DEF-006 e anti-injeção CT-026)
- Modo Híbrido: executa localmente sobre os `SingleTurnSample` sem exigir chave de API,
  e suporta execução online com `gpt-4o-mini` quando `OPENAI_API_KEY` está configurada.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

import ragas
from ragas.dataset_schema import EvaluationDataset, SingleTurnSample

from evals.dataset_jarvis import CasoAvaliacaoJarvis, construir_golden_dataset
from evals.metricas_jarvis import (
    avaliar_aderencia_dados,
    avaliar_reducao_alucinacao,
    avaliar_regras_texto,
    julgar_com_llm_ou_local,
    tem_openai_api_key,
)


def construir_ragas_dataset(casos: List[CasoAvaliacaoJarvis] | None = None) -> EvaluationDataset:
    """Converte o Golden Dataset do Jarvis para `ragas.dataset_schema.EvaluationDataset`."""
    dataset = casos or construir_golden_dataset()
    amostras: List[SingleTurnSample] = []
    for c in dataset:
        amostras.append(
            SingleTurnSample(
                user_input=c.pergunta,
                retrieved_contexts=c.contexto_recuperado,
                response=c.output_modelo,
                reference=c.resposta_esperada,
            )
        )
    return EvaluationDataset(samples=amostras)


def avaliar_amostra_ragas(
    amostra: SingleTurnSample,
    caso_meta: CasoAvaliacaoJarvis,
    forcar_offline: bool = False,
) -> Dict[str, Any]:
    """
    Avalia um `SingleTurnSample` do Ragas calculando:
    - `faithfulness` (aderência das afirmações da resposta ao `retrieved_contexts`)
    - `factual_correctness` (alinhamento com `reference` e ausência de alucinação no fallback)
    - `aspect_critic_persona` (cumprimento das regras de texto e persona 'senhor')
    """
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
    """
    Executa a avaliação com Ragas (`EvaluationDataset` + `SingleTurnSample`)
    sobre todos os casos do Golden Dataset.
    """
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
        "versao": getattr(ragas, "__version__", "0.4.4"),
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
    print(f"=== Ragas v{relatorio['versao']} ({relatorio['schema_utilizado']}) ===")
    print(
        f"Casos avaliados: {relatorio['total_casos']} | "
        f"Acurácia de detecção (PASS/FAIL): {relatorio['acuracia_deteccao']*100:.1f}% | "
        f"Tempo: {relatorio['tempo_execucao_ms']} ms"
    )
    for c in relatorio["casos"]:
        status = "PASS" if c["aprovado_obtido"] else "FAIL"
        esperado = "PASS" if c["esperado_aprovado"] else "FAIL"
        check = "OK" if c["detectou_corretamente"] else "DIVERGENTE"
        print(
            f"  [{c['id']}] ({c['categoria']}) -> Obtido: {status} | Esperado: {esperado} [{check}] "
            f"| Ragas: {c['metricas_ragas']}"
        )
