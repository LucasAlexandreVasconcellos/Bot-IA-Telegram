import pytest
from prompt_gateway import (
    SKILLS,
    classificar_intencao,
    montar_prompt_sob_demanda,
)

@pytest.mark.parametrize(
    "mensagem, intencao_esperada",
    [
        ("Oi!", "saudacao"),
        ("Bom dia, tudo bem?", "saudacao"),
        ("", "saudacao"),
        ("Qual o faturamento líquido de agosto?", "consulta_simples"),
        ("Me mostra o ROI do marketing", "consulta_simples"),
        ("Qual a probabilidade de atingir a meta e o intervalo de confiança?", "probabilistica"),
        ("Faça uma projeção de cenários futuros de vendas", "probabilistica"),
        ("Quero um boxplot com a distribuição e outliers das vendas", "estatistica_seaborn"),
        ("Gere um gráfico de barras das lojas", "grafico_padrao"),
    ],
)
def test_classificacao_intencoes(mensagem, intencao_esperada):
    assert classificar_intencao(mensagem) == intencao_esperada


def test_consulta_simples_nao_carrega_skills_pesadas():
    res = montar_prompt_sob_demanda("Qual o total de vendas da Loja Centro?")
    assert res.intencao == "consulta_simples"
    assert res.skills_carregadas == ["skill_sql_seguro"]
    assert "[SKILL PROBABILÍSTICA]" not in res.prompt_sistema
    assert "[SKILL ESTATÍSTICA / SEABORN]" not in res.prompt_sistema
    assert "[SKILL GRÁFICO]" not in res.prompt_sistema
    assert res.economia_percentual > 50.0


def test_probabilistica_carrega_apenas_sql_e_probabilidade():
    res = montar_prompt_sob_demanda("Calcule o intervalo de confiança do faturamento")
    assert res.skills_carregadas == ["skill_sql_seguro", "skill_probabilistica"]
    assert "[SKILL PROBABILÍSTICA]" in res.prompt_sistema
    assert "[SKILL ESTATÍSTICA / SEABORN]" not in res.prompt_sistema


def test_saudacao_nao_carrega_sql():
    res = montar_prompt_sob_demanda("Olá")
    assert res.skills_carregadas == ["skill_sem_consulta"]
    assert "[SKILL SQL]" not in res.prompt_sistema
    assert res.tokens_estimados_gateway < res.tokens_estimados_monolitico