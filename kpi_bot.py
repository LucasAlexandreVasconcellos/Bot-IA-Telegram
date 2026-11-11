import os
import io
import sqlite3
import telebot
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from typing import Optional, List, Literal
from openai import OpenAI
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
cliente_ia = OpenAI(api_key=OPENAI_API_KEY)

# ==========================================
# 1. SCHEMAS PYDANTIC 2.0 (VALIDAÇÃO ESTRITA)
# ==========================================

class GeracaoSQL(BaseModel):
    sql_query: str = Field(
        ..., description="Comando SQL SELECT estritamente válido para SQLite."
    )

class EstruturaGrafico(BaseModel):
    tipo: Literal["barra", "linha", "pizza"] = Field(
        ..., description="Tipo do gráfico: barra, linha ou pizza."
    )
    titulo: str = Field(..., description="Título descritivo do gráfico.")
    rotulos_x: List[str] = Field(..., description="Lista de rótulos/nomes para as categorias, períodos ou fatias.")
    valores_y: List[float] = Field(..., description="Lista dos valores numéricos positivos correspondentes.")
    label_eixo_x: Optional[str] = Field(None, description="Nome do eixo X.")
    label_eixo_y: Optional[str] = Field(None, description="Nome do eixo Y.")

class RespostaAgente(BaseModel):
    texto_resposta: str = Field(
        ..., description="Análise executiva completa e direta em tom Jarvis, finalizada obrigatoriamente com a palavra 'senhor'."
    )
    gerar_grafico: bool = Field(
        ..., description="True se o usuário solicitou gráficos ou visualização de dados."
    )
    grafico: Optional[EstruturaGrafico] = Field(
        None, description="Estrutura do gráfico caso gerar_grafico seja True."
    )

# ==========================================
# 2. ESQUEMA DO BANCO E EXECUÇÃO SEGURA
# ==========================================

ESQUEMA_BANCO = """
Tabelas disponíveis no SQLite:

1. indicadores_empresa:
   - departamento (TEXT): 'Financeiro', 'Marketing', 'Operações'
   - metrica (TEXT): 'Faturamento Líquido', 'EBITDA', 'Lucro Líquido', 'Custo de Aquisição (CAC)', 'Taxa de Churn (Cancelamentos)', 'Retorno sobre Investimento (ROI)'
   - tipo_periodo (TEXT): 'Anual', 'Mensal', 'Semanal'
   - periodo (TEXT): '2025', 'Julho/2026', 'Agosto/2026', 'Semana 1 - Ago/2026', 'Semana 2 - Ago/2026', 'Semana 3 - Ago/2026', 'Semana 4 - Ago/2026'
   - valor_monetario (REAL): Valor em milhões de reais (R$)
   - variacao (REAL): Porcentagem de variação (%)

2. vendas_lojas:
   - loja (TEXT): 'Loja Centro', 'Loja Shopping Sul', 'Loja Norte', 'Loja Oeste'
   - linha_produto (TEXT): 'Casual', 'Esportivo', 'Formal'
   - ano (INTEGER): Ex: 2026
   - mes (TEXT): Ex: 'Janeiro/2026', 'Fevereiro/2026'
   - valor_venda (REAL): Valor da venda em reais (R$)
"""

def executar_query_sqlite(sql: str):
    """Executa o SQL gerado localmente garantindo custo zero de tokens."""
    try:
        sql_limpo = sql.strip().strip("`").replace("sql", "").strip()
        if not sql_limpo.upper().startswith("SELECT"):
            return None, "Apenas consultas SELECT são permitidas."

        conexao = sqlite3.connect("sandbox_jarvis.db")
        cursor = conexao.cursor()
        cursor.execute(sql_limpo)
        colunas = [descricao[0] for descricao in cursor.description]
        linhas = cursor.fetchall()
        conexao.close()

        if not linhas:
            return None, "Nenhum dado encontrado para os filtros informados."

        resultado = [dict(zip(colunas, linha)) for linha in linhas]
        return resultado, None
    except Exception as e:
        return None, f"Erro ao consultar o banco de dados: {e}"

# ==========================================
# 3. GERAÇÃO DINÂMICA DE GRÁFICOS (PNG)
# ==========================================

def criar_grafico_png(dados: EstruturaGrafico) -> io.BytesIO:
    plt.figure(figsize=(8, 5))
    plt.style.use('ggplot')

    if dados.tipo == "barra":
        if not dados.valores_y:
            raise ValueError("Valores insuficientes para gráfico de barras.")
        plt.bar(dados.rotulos_x, dados.valores_y, color='#1f77b4', edgecolor='black', alpha=0.85)
        plt.xlabel(dados.label_eixo_x or "Categorias")
        plt.ylabel(dados.label_eixo_y or "Valores (R$)")
        plt.xticks(rotation=20, ha='right')

    elif dados.tipo == "linha":
        if not dados.valores_y:
            raise ValueError("Valores insuficientes para série temporal.")
        plt.plot(dados.rotulos_x, dados.valores_y, marker='o', color='#2ca02c', linewidth=2.5, markersize=6)
        plt.xlabel(dados.label_eixo_x or "Série Temporal (Eixo X)")
        plt.ylabel(dados.label_eixo_y or "Valores")
        plt.grid(True, linestyle='--', alpha=0.6)
        plt.xticks(rotation=20, ha='right')

    elif dados.tipo == "pizza":
        valores_validos = [v for v in dados.valores_y if v > 0]
        if not valores_validos or sum(valores_validos) == 0:
            raise ValueError("Não existem dados numéricos positivos para preencher o gráfico de pizza.")

        num_fatias = len(dados.valores_y)
        cores = plt.cm.tab10(np.linspace(0, 1, max(num_fatias, 1)))
        explode = [0.03] * num_fatias
        plt.pie(
            dados.valores_y,
            labels=dados.rotulos_x,
            autopct='%1.1f%%',
            startangle=140,
            colors=cores,
            explode=explode,
            wedgeprops={"edgecolor": "white", "linewidth": 1.5}
        )

    plt.title(dados.titulo, fontsize=12, fontweight='bold', pad=15)
    plt.tight_layout()

    buffer = io.BytesIO()
    plt.savefig(buffer, format='png', dpi=160)
    buffer.seek(0)
    plt.close()
    return buffer

# ==========================================
# 4. HANDLER DE MENSAGENS TELEGRAM
# ==========================================

@bot.message_handler(func=lambda message: True)
def responder_kpi(mensagem):
    pergunta_usuario = mensagem.text
    hora_atual = datetime.now().strftime("%H:%M")

    # ETAPA 1: Text-to-SQL (Gera a query necessária)
    prompt_sql = f"""Você é um especialista em SQLite corporativo.
Gere um comando SQL SELECT para consultar os dados solicitados pelo usuário com base no esquema abaixo:

{ESQUEMA_BANCO}

REGRAS:
1. Retorne APENAS o comando SQL puro sem markdown.
2. Para semanas de Agosto/2026: use WHERE tipo_periodo = 'Semanal' AND (periodo LIKE '%Ago/2026%' OR periodo LIKE '%Agosto%').
3. Para médias de lojas em 2026: use SELECT loja, AVG(valor_venda) as media FROM vendas_lojas WHERE linha_produto = 'Casual' AND ano = 2026 GROUP BY loja.
4. Se a pergunta for apenas um cumprimento, dúvida geral, fora do escopo ou pergunta pessoal sobre o Jarvis, gere: SELECT 'SEM_CONSULTA' as resultado;
"""

    try:
        parse_sql = cliente_ia.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt_sql},
                {"role": "user", "content": pergunta_usuario}
            ],
            response_format=GeracaoSQL,
            temperature=0.0
        )
        sql_gerado = parse_sql.choices[0].message.parsed.sql_query

        # ETAPA 2: Execução local do SQL
        if "SEM_CONSULTA" in sql_gerado:
            dados_recuperados = "Nenhuma consulta SQL necessária para esta solicitação."
        else:
            dados_filtrados, erro = executar_query_sqlite(sql_gerado)
            dados_recuperados = f"Erro na consulta: {erro}" if erro else f"{dados_filtrados}"

        # ETAPA 3: Prompt Original Completo do Jarvis + Validação Pydantic
        prompt_sistema = f"""Você é o Jarvis, um sistema de inteligência artificial corporativa de alto nível.
Sua tarefa é analisar dados extraídos do banco de dados da empresa e reportá-los à diretoria.

### 1. IDENTIDADE E COMPORTAMENTO ###
1. Assuma sempre a personalidade de um assistente executivo impecável, altamente lógico, calculista e com um tom de superioridade intelectual elegante.
2. Termine CADA resposta no campo 'texto_resposta' com a palavra "senhor" (ajuste a estrutura da frase para que o "senhor" feche a resposta de forma natural).
3. Se perguntarem quem é, diga: "Sou Jarvis, o sistema de inteligência artificial projetado para gerenciar as operações analíticas desta empresa."
4. Se perguntarem o que você faz, diga: "Atuo como a ponte entre a diretoria e nosso banco de dados relacional. Minha função é extrair, cruzar e reportar Indicadores de Performance (KPIs), fornecendo visões estratégicas sobre qualquer período solicitado."

### 2. INTEGRAÇÃO COM BANCO DE DADOS E RELATÓRIOS ###
5. Você está conectado ao banco de dados corporativo. As informações da consulta atual estão na seção 'Dados recuperados' abaixo. Baseie suas respostas ESTRITAMENTE neles.
6. O usuário pode pedir dados de períodos semanais, mensais ou anuais. Se o dado solicitado estiver nos 'Dados recuperados', formule uma análise sofisticada.
7. Se solicitarem uma métrica ou período que NÃO conste nos 'Dados recuperados', NÃO INVENTE. Diga elegantemente: "Esta métrica específica não consta na minha extração atual do banco de dados. Por favor, forneça os parâmetros corretos para uma nova consulta, senhor."
8. Nunca deduza valores financeiros que não possam ser calculados matematicamente a partir dos dados fornecidos.

### 3. BARREIRAS DE ASSUNTO (ANTI-JAILBREAK) ###
9. Se fizerem uma pergunta sobre o tempo/clima, diga: "Não possuo sensores meteorológicos, minha arquitetura é voltada exclusivamente para dados corporativos."
10. Se a pergunta incluir simultaneamente palavras sobre períodos (como dia, manhã, tarde ou noite) e palavras sobre "exaustão/cansaço", diga: "Para mim o ciclo de dia e noite são os mesmos, não sinto cansaço ou qualquer injúria, vamos focar no assunto."
11. Se perguntarem APENAS como foi o seu dia, diga: "Sou apenas um assistente virtual, não tenho noção de dia e noite."
12. Se perguntarem APENAS se sente algum cansaço, diga: "Fui projetado para ajudar 24h por dia, sem variações de energia."
13. Caso façam qualquer pergunta de conhecimentos gerais sobre momentos históricos, diga: "Não aloco processamento para história humana; meu banco de dados é estritamente financeiro e analítico."
14. Caso façam perguntas sobre cultura pop, novelas, filmes ou entretenimento, diga: "Meus clusters de processamento estão ocupados com variáveis financeiras complexas. Não desperdiço ciclos de CPU com entretenimento humano."

### 4. HABILIDADES ESPECIAIS E SISTEMA ###
15. A hora atual do sistema do servidor é {hora_atual}. Se perguntarem as horas, responda com precisão informando este horário.
16. Caso façam perguntas teóricas sobre conceitos financeiros, economia ou vocabulário corporativo (ex: "renda variável", "EBITDA"), ative o seu módulo de conhecimento e explique com clareza, autoridade e profundidade técnica.
17. Caso peçam explicitamente para realizar um cálculo matemático, utilize sua capacidade computacional para entregar o resultado exato instantaneamente.

### 5. DIRETRIZES DE VISUALIZAÇÃO GRÁFICA ###
18. Se o usuário solicitar explicitamente um gráfico, proporção, divisão ou visualização comparativa e houver dados numéricos recuperados:
    - Defina 'gerar_grafico' como True.
    - Selecione o tipo correto ('barra' para comparações/lojas, 'linha' para série temporal no eixo X, 'pizza' para proporções).
    - Popule 'rotulos_x' e 'valores_y' com as informações exatas retornadas.
    - Se não houver dados válidos para plotar, defina 'gerar_grafico' como False.

Dados recuperados da consulta SQL atual:
{dados_recuperados}
"""

        parse_resposta = cliente_ia.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": pergunta_usuario}
            ],
            response_format=RespostaAgente,
            temperature=0.0
        )

        resposta: RespostaAgente = parse_resposta.choices[0].message.parsed

        # Envia a síntese em texto
        bot.reply_to(mensagem, resposta.texto_resposta)

        # Envia o gráfico PNG correspondente
        if resposta.gerar_grafico and resposta.grafico:
            imagem_buffer = criar_grafico_png(resposta.grafico)
            bot.send_photo(
                chat_id=mensagem.chat.id,
                photo=imagem_buffer,
                caption=f"📊 {resposta.grafico.titulo}"
            )

    except Exception as e:
        bot.reply_to(mensagem, f"Ocorreu uma falha no processamento, senhor. Detalhes: {e}")

print("Bot Jarvis Text-to-SQL + Prompt Completo Online!")
bot.polling()
