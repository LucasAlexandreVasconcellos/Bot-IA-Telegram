import re
import unicodedata
from typing import Dict, List, Literal
from pydantic import BaseModel, Field

# ==========================================================
# 1. SCHEMAS DE SAÍDA DO GATEWAY (Pydantic 2.0)
# ==========================================================

TipoIntencao = Literal[
    "saudacao",
    "consulta_simples",
    "probabilistica",
    "estatistica_seaborn",
    "grafico_padrao",
]

class ResultadoGateway(BaseModel):
    intencao: TipoIntencao
    skills_carregadas: List[str]
    prompt_sistema: str
    tokens_estimados_gateway: int
    tokens_estimados_monolitico: int
    economia_percentual: float = Field(..., ge=0.0, le=100.0)


# ==========================================================
# 2. CATÁLOGO DE SKILLS / REGRAS MODULARES (Sob Demanda)
# ==========================================================

REGRA_BASE = (
    "Você é o Jarvis, assistente analítico corporativo. Responda em português "
    "de forma direta e executiva, usando apenas os dados fornecidos pelo banco."
)

SKILLS: Dict[str, str] = {
    "skill_sql_seguro": (
        "[SKILL SQL] Gere apenas consultas SELECT válidas para SQLite/PostgreSQL. "
        "Nunca execute comandos de escrita (INSERT, UPDATE, DELETE, DROP). "
        "Tabelas disponíveis: indicadores_empresa(departamento, metrica, tipo_periodo, "
        "periodo, valor_monetario, variacao) e vendas_lojas(loja, linha_produto, ano, mes, valor_venda)."
    ),
    "skill_probabilistica": (
        "[SKILL PROBABILÍSTICA] Acione as ferramentas probabilísticas do agente para "
        "calcular estimativas de cenários (otimista, realista, pessimista), intervalos "
        "de confiança e pontuação de incerteza com base na série histórica."
    ),
    "skill_estatistica_seaborn": (
        "[SKILL ESTATÍSTICA / SEABORN] Acione o gerador estatístico com Seaborn/Pandas "
        "para calcular distribuição, mediana, quartis (boxplot/histograma/dispersão) "
        "e enviar a imagem gerada junto com a interpretação dos outliers."
    ),
    "skill_grafico_padrao": (
        "[SKILL GRÁFICO] Defina gerar_grafico=True e preencha EstruturaGrafico "
        "(tipo: 'barra', 'linha' ou 'pizza', titulo, rotulos_x e valores_y)."
    ),
    "skill_sem_consulta": (
        "[SKILL CONVERSA] Nenhuma consulta SQL é necessária. Retorne "
        "SELECT 'SEM_CONSULTA' AS resultado; e responda cordialmente."
    ),
}

# Mapa de quais skills cada intenção exige
ROTEAMENTO_SKILLS: Dict[TipoIntencao, List[str]] = {
    "saudacao": ["skill_sem_consulta"],
    "consulta_simples": ["skill_sql_seguro"],
    "probabilistica": ["skill_sql_seguro", "skill_probabilistica"],
    "estatistica_seaborn": ["skill_sql_seguro", "skill_estatistica_seaborn"],
    "grafico_padrao": ["skill_sql_seguro", "skill_grafico_padrao"],
}


# ==========================================================
# 3. MOTOR DE CLASSIFICAÇÃO DE INTENÇÃO (Zero Latência)
# ==========================================================

def _normalizar_texto(texto: str) -> str:
    """Remove acentos, coloca em minúsculas e limpa espaços extras."""
    texto = texto.strip().lower()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", texto)


PADROES_INTENCAO: List[tuple[TipoIntencao, List[str]]] = [
    (
        "saudacao",
        [
            r"^(oi|ola|bom dia|boa tarde|boa noite|e ai|tudo bem|ajuda|menu|start|/start)([,!?\s]+(tudo bem|jarvis|pessoal|galera|oi|ola))*[!?.\s]*$",
        ],
    ),
    (
        "probabilistica",
        [
            r"\b(probabilidad\w*|previs\w*|projec\w*|cenario\w*|intervalo de confianca|incerteza|risco|simula\w*|monte carlo|tendencia futura)\b",
        ],
    ),
    (
        "estatistica_seaborn",
        [
            r"\b(seaborn|distribuic\w*|boxplot|histograma|correlac\w*|dispers\w*|quartil\w*|outlier\w*|desvio padrao|variancia|analise estatistica)\b",
        ],
    ),
    (
        "grafico_padrao",
        [
            r"\b(grafic\w*|plot\w*|visualiz\w*|pizza|barra\w*|linha\w*|comparativo visual)\b",
        ],
    ),
]


def classificar_intencao(mensagem: str) -> TipoIntencao:
    """Identifica a intenção da mensagem antes de montar o prompt."""
    if not mensagem or not mensagem.strip():
        return "saudacao"

    texto_limpo = _normalizar_texto(mensagem)

    for intencao, padroes in PADROES_INTENCAO:
        for padrao in padroes:
            if re.search(padrao, texto_limpo):
                return intencao

    return "consulta_simples"


# ==========================================================
# 4. MONTAGEM DO PROMPT SOB DEMANDA E MÉTRICA DE ECONOMIA
# ==========================================================

def _estimar_tokens(texto: str) -> int:
    """Estimativa padrão de tokens para modelos OpenAI (~4 caracteres por token)."""
    return max(1, round(len(texto) / 4))


def montar_prompt_sob_demanda(mensagem: str) -> ResultadoGateway:
    """
    Roteador principal: classifica a intenção, carrega apenas as skills
    necessárias e calcula a economia de tokens em relação ao prompt monolítico.
    """
    intencao = classificar_intencao(mensagem)
    skills_selecionadas = ROTEAMENTO_SKILLS[intencao]

    blocos_ativos = [REGRA_BASE] + [SKILLS[s] for s in skills_selecionadas]
    prompt_enxuto = "\n\n".join(blocos_ativos)

    # Prompt monolítico (caso todas as regras fossem enviadas sempre)
    prompt_completo = "\n\n".join([REGRA_BASE] + list(SKILLS.values()))

    tokens_gateway = _estimar_tokens(prompt_enxuto)
    tokens_total = _estimar_tokens(prompt_completo)
    economia = round((1 - (tokens_gateway / tokens_total)) * 100, 1)

    return ResultadoGateway(
        intencao=intencao,
        skills_carregadas=skills_selecionadas,
        prompt_sistema=prompt_enxuto,
        tokens_estimados_gateway=tokens_gateway,
        tokens_estimados_monolitico=tokens_total,
        economia_percentual=max(0.0, economia),
    )


if __name__ == "__main__":
    exemplos = [
        "Oi, tudo bem?",
        "Qual foi o faturamento líquido do financeiro em agosto?",
        "Qual a probabilidade e o intervalo de confiança de batermos a meta no próximo mês?",
        "Gere uma análise estatística com boxplot da distribuição de vendas por loja",
        "Mostre um gráfico de barras comparando as vendas por loja",
    ]
    for msg in exemplos:
        res = montar_prompt_sob_demanda(msg)
        print(f"Mensagem: {msg}")
        print(f"  -> Intenção: {res.intencao} | Skills: {res.skills_carregadas}")
        print(f"  -> Tokens: {res.tokens_estimados_gateway}/{res.tokens_estimados_monolitico} (Economia: {res.economia_percentual}%)\n")