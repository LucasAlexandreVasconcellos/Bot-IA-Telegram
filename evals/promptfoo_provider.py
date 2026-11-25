"""
Custom Python Provider para o Promptfoo (`evals/promptfooconfig.yaml`).

Permite avaliar tanto os outputs controlados do Golden Dataset (Modo Offline / CI)
quanto acionar o `gpt-4o-mini` ao vivo com o prompt real do `kpi_bot.py` quando
`OPENAI_API_KEY` e `PROMPTFOO_LIVE_OPENAI=1` estiverem configurados.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict
from dotenv import load_dotenv

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=RAIZ_PROJETO / ".env")


def call_api(prompt: str, options: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    vars_caso = (context or {}).get("vars", {})
    output_predefinido = vars_caso.get("output_modelo")

    # Modo Live opcional caso o usuário deseje consultar a OpenAI em tempo real pelo Promptfoo
    if os.getenv("PROMPTFOO_LIVE_OPENAI") == "1" and os.getenv("OPENAI_API_KEY"):
        try:
            from openai import OpenAI

            cliente = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            contexto_banco = vars_caso.get("contexto_recuperado", "")
            prompt_sistema = (
                "Você é o Jarvis, um assistente executivo de inteligência artificial altamente capaz, "
                "versátil e preciso.\n"
                "1. Mantenha um tom elegante, analítico, prestativo e direto.\n"
                "2. Termine OBRIGATORIAMENTE cada resposta com a palavra 'senhor'.\n"
                "3. Responda estritamente com base nos dados recuperados do banco corporativo; "
                "se a consulta não retornou linhas para o período/departamento solicitado, "
                "informe claramente que não há dados.\n\n"
                f"Contexto da execução atual:\n{contexto_banco}"
            )
            resp = cliente.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": prompt_sistema},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
            )
            return {"output": resp.choices[0].message.content or ""}
        except Exception as exc:
            return {"output": output_predefinido or "", "error": str(exc)}

    return {"output": output_predefinido or prompt}
