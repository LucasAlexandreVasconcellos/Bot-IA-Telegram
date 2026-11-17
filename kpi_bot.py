import os
import json
import base64
import telebot
from typing import Optional, List, Literal
from openai import OpenAI
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from datetime import datetime

# Import da camada de sandbox e execução isolada (Integrante 1)
from sandbox_ambiente.executor_sandbox import executar_codigo_sandbox

# Import da camada de qualidade de dados (Integrante 2)
from qualidade_dados import sanitizar_linhas_consulta

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
cliente_ia = OpenAI(api_key=OPENAI_API_KEY)

# ==========================================
# 1. SCHEMAS PYDANTIC 2.0 (VALIDAÇÃO ESTRITA)
# ==========================================

class RoteamentoConsulta(BaseModel):
    tipo_solicitacao: Literal["banco_dados", "geral_ou_externo"] = Field(
        ...,
        description="Use 'banco_dados' se a pergunta envolver indicadores da empresa, faturamento, EBITDA, lucro, CAC, churn, ROI, lojas ou vendas internas. Use 'geral_ou_externo' para perguntas gerais, conceitos, cálculos, saudações ou gráficos sobre temas externos (ex: economia global)."
    )
    sql_query: str = Field(
        ...,
        description="Comando SQL SELECT flexível usando LIKE para SQLite caso tipo_solicitacao seja 'banco_dados'. Caso contrário, retorne 'SELECT 1'."
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
        ..., description="Resposta executiva completa, direta e inteligente em tom Jarvis, finalizada obrigatoriamente com a palavra 'senhor'."
    )
    gerar_grafico: bool = Field(
        ..., description="True se o usuário solicitou gráfico, visualização ou comparação visual."
    )
    grafico: Optional[EstruturaGrafico] = Field(
        None, description="Dados estruturados para renderizar o gráfico caso gerar_grafico seja True."
    )

# ==========================================
# 2. ESQUEMA DO BANCO E EXECUÇÃO NA SANDBOX
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

def rodar_sql_isolado(sql_limpo: str):
    """Executa uma query SQL dentro da Sandbox e retorna os registros higienizados."""
    codigo_consulta = f"""
import json
import base64

conexao = sqlite3.connect("dados_sandbox.db")
conexao.text_factory = bytes
cursor = conexao.cursor()
cursor.execute({repr(sql_limpo)})
colunas = [desc[0].decode('utf-8', errors='replace') if isinstance(desc[0], bytes) else desc[0] for desc in cursor.description]
linhas = cursor.fetchall()
conexao.close()

registros_serializados = []
for linha in linhas:
    item = {{}}
    for col, val in zip(colunas, linha):
        if isinstance(val, bytes):
            item[col] = {{"__bytes__": base64.b64encode(val).decode('ascii')}}
        else:
            item[col] = val
    registros_serializados.append(item)

print(json.dumps(registros_serializados))
"""
    res_sandbox = executar_codigo_sandbox(
        codigo_python=codigo_consulta,
        caminho_banco="sandbox_jarvis.db",
        timeout_segundos=10
    )

    if not res_sandbox["sucesso"] or not res_sandbox["saida"]:
        return [], 0, res_sandbox["erro"]

    registros_brutos = json.loads(res_sandbox["saida"])
    if not registros_brutos:
        return [], 0, None

    resultado_bruto = []
    for reg in registros_brutos:
        linha_reconstruida = {}
        for col, val in reg.items():
            if isinstance(val, dict) and "__bytes__" in val:
                linha_reconstruida[col] = base64.b64decode(val["__bytes__"])
            else:
                linha_reconstruida[col] = val
        resultado_bruto.append(linha_reconstruida)

    dados_higienizados, qtd_isolados = sanitizar_linhas_consulta(resultado_bruto)
    return dados_higienizados, qtd_isolados, None

def executar_query_sqlite(sql: str):
    """Executa a query principal na Sandbox com fallback automático caso o filtro seja restritivo demais."""
    try:
        sql_limpo = sql.strip().strip("`").replace("sql", "").strip()
        if not sql_limpo.upper().startswith("SELECT"):
            return None, "Apenas consultas SELECT são permitidas."

        print(f"[SANDBOX] Executando SQL: {sql_limpo}")
        dados, isolados, erro = rodar_sql_isolado(sql_limpo)

        if erro:
            return None, f"Erro na execução SQL: {erro}"

        # Fallback inteligente: se a query específica veio vazia, carrega visão geral das tabelas
        # para que a IA explique o que existe disponível em vez de travar
        if not dados:
            print("[SANDBOX] Consulta específica vazia. Acionando varredura ampla de contexto...")
            ind_dados, ind_iso, _ = rodar_sql_isolado("SELECT * FROM indicadores_empresa LIMIT 25")
            vnd_dados, vnd_iso, _ = rodar_sql_isolado("SELECT * FROM vendas_lojas LIMIT 25")
            return {
                "dados": {
                    "aviso": "A busca exata não retornou linhas, mas aqui está o conteúdo completo disponível no banco para você responder ao usuário com precisão:",
                    "indicadores_empresa": ind_dados,
                    "vendas_lojas": vnd_dados
                },
                "isolados": ind_iso + vnd_iso
            }, None

        return {
            "dados": dados,
            "isolados": isolados
        }, None
    except Exception as e:
        return None, f"Erro ao consultar o banco de dados via Sandbox: {e}"

# ==========================================
# 3. GERAÇÃO ISOLADA DE GRÁFICOS NA SANDBOX
# ==========================================

def criar_grafico_sandbox(dados: EstruturaGrafico) -> str:
    """Renderiza o gráfico em subprocesso isolado na Sandbox e retorna o caminho do PNG salvo."""
    nome_arquivo = f"grafico_jarvis_{int(datetime.now().timestamp())}.png"

    codigo_grafico = f"""
import numpy as np

tipo = {repr(dados.tipo)}
titulo = {repr(dados.titulo)}
rotulos_x = {repr(dados.rotulos_x)}
valores_y = {repr(dados.valores_y)}
label_x = {repr(dados.label_eixo_x)}
label_y = {repr(dados.label_eixo_y)}

min_len = min(len(rotulos_x), len(valores_y))
rotulos_x = rotulos_x[:min_len]
valores_y = valores_y[:min_len]

plt.figure(figsize=(8, 5))
plt.style.use('ggplot')

if tipo == "barra":
    if not valores_y:
        raise ValueError("Valores insuficientes para gráfico de barras.")
    plt.bar(rotulos_x, valores_y, color='#1f77b4', edgecolor='black', alpha=0.85)
    plt.xlabel(label_x or "Categorias")
    plt.ylabel(label_y or "Valores")
    plt.xticks(rotation=20, ha='right')

elif tipo == "linha":
    if not valores_y:
        raise ValueError("Valores insuficientes para série temporal.")
    plt.plot(rotulos_x, valores_y, marker='o', color='#2ca02c', linewidth=2.5, markersize=6)
    plt.xlabel(label_x or "Série Temporal")
    plt.ylabel(label_y or "Valores")
    plt.grid(True, linestyle='--', alpha=0.6)
    plt.xticks(rotation=20, ha='right')

elif tipo == "pizza":
    valores_validos = [v for v in valores_y if v > 0]
    if not valores_validos or sum(valores_validos) == 0:
        raise ValueError("Não existem dados numéricos positivos para preencher o gráfico de pizza.")

    num_fatias = len(valores_y)
    cores = plt.cm.tab10(np.linspace(0, 1, max(num_fatias, 1)))
    explode = [0.03] * num_fatias
    plt.pie(
        valores_y,
        labels=rotulos_x,
        autopct='%1.1f%%',
        startangle=140,
        colors=cores,
        explode=explode,
        wedgeprops={{"edgecolor": "white", "linewidth": 1.5}}
    )

plt.title(titulo, fontsize=12, fontweight='bold', pad=15)
plt.tight_layout()
plt.savefig({repr(nome_arquivo)}, dpi=160)
plt.close()
"""
    print("[SANDBOX] Renderizando gráfico em ambiente isolado...")
    res_sandbox = executar_codigo_sandbox(
        codigo_python=codigo_grafico,
        pasta_saida_graficos="charts",
        timeout_segundos=15
    )

    if not res_sandbox["sucesso"] or not res_sandbox["grafico_gerado"]:
        raise RuntimeError(f"Falha ao gerar gráfico na Sandbox: {res_sandbox['erro']}")

    return res_sandbox["grafico_gerado"]

# ==========================================
# 4. HANDLER DE MENSAGENS TELEGRAM
# ==========================================

@bot.message_handler(func=lambda message: True)
def responder_kpi(mensagem):
    pergunta_usuario = mensagem.text
    hora_atual = datetime.now().strftime("%H:%M")

    prompt_roteamento = f"""Você é um roteador analítico especialista em SQLite e Ciência de Dados.
Analise a pergunta do usuário e decida se ela exige consulta ao banco de dados corporativo ou se é uma pergunta geral/externa.

Esquema do banco corporativo:
{ESQUEMA_BANCO}

REGRAS PARA SQL (quando tipo_solicitacao = 'banco_dados'):
1. Use sempre buscas flexíveis com LIKE para textos e períodos (ex: WHERE metrica LIKE '%Faturamento%' AND periodo LIKE '%2026%').
2. NÃO restrinja tipo_periodo = 'Anual' se o usuário pedir um ano como 2026, pois 2026 pode ter apenas dados mensais ou semanais. Busque todos os registros daquele ano (periodo LIKE '%2026%').
3. Para vendas de lojas, lembre-se que o campo mes tem formato 'Janeiro/2026', então use mes LIKE '%Janeiro%'.
4. Se a pergunta for sobre economia global, conhecimentos gerais, finanças teóricas, cálculos matemáticos, programação ou saudações, defina tipo_solicitacao = 'geral_ou_externo'.
"""

    try:
        roteamento = cliente_ia.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt_roteamento},
                {"role": "user", "content": pergunta_usuario}
            ],
            response_format=RoteamentoConsulta,
            temperature=0.0
        ).choices[0].message.parsed

        if roteamento.tipo_solicitacao == "geral_ou_externo":
            contexto_dados = "Solicitação de conhecimento geral, cálculo ou tema externo ao banco corporativo. Responda usando sua base de conhecimento analítico."
        else:
            resultado_consulta, erro = executar_query_sqlite(roteamento.sql_query)
            if erro:
                contexto_dados = f"Falha técnica na consulta: {erro}"
            else:
                contexto_dados = (
                    f"Dados recuperados do banco corporativo (validados pela camada de qualidade): {resultado_consulta['dados']}. "
                    f"Registros corrompidos isolados: {resultado_consulta['isolados']}."
                )

        prompt_sistema = f"""Você é o Jarvis, um assistente executivo de inteligência artificial altamente capaz, versátil e preciso.

### DIRETRIZES DE COMPORTAMENTO ###
1. Mantenha um tom elegante, analítico, prestativo e direto.
2. Termine OBRIGATORIAMENTE cada resposta no campo 'texto_resposta' com a palavra "senhor".
3. Você está apto a responder QUALQUER pergunta:
   - **Consultas Corporativas:** Analise os dados recuperados do banco com precisão. Se o usuário pedir um consolidado anual (ex: 2026) e o banco contiver apenas dados mensais/semanais daquele ano, apresente os valores disponíveis e calcule a soma ou média correspondente deixando claro o período.
   - **Conhecimentos Gerais, Economia, Tecnologia, História, Clima ou Cálculos:** Responda de forma completa, clara e informativa utilizando seu conhecimento amplo. Nunca recuse perguntas por estarem fora do banco de dados.
   - **Hora do servidor:** Agora são {hora_atual}.
4. **Gráficos Dinâmicos (Internos ou Externos):**
   - Sempre que o usuário pedir um gráfico, visualização ou comparação (seja sobre dados da empresa OU sobre temas gerais como economia global, PIB, tecnologias, etc.), defina 'gerar_grafico' como True.
   - Escolha o melhor tipo ('barra', 'linha' ou 'pizza'), preencha 'rotulos_x' e 'valores_y' com números reais/estimados coerentes e informe na resposta a origem dos dados (banco interno ou estimativa de mercado).

Contexto da execução atual:
{contexto_dados}
"""

        resposta: RespostaAgente = cliente_ia.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": pergunta_usuario}
            ],
            response_format=RespostaAgente,
            temperature=0.2
        ).choices[0].message.parsed

        bot.reply_to(mensagem, resposta.texto_resposta)

        if resposta.gerar_grafico and resposta.grafico:
            caminho_imagem = criar_grafico_sandbox(resposta.grafico)
            with open(caminho_imagem, "rb") as foto:
                bot.send_photo(
                    chat_id=mensagem.chat.id,
                    photo=foto,
                    caption=f"📊 {resposta.grafico.titulo}"
                )

    except Exception as e:
        bot.reply_to(mensagem, f"Ocorreu uma falha no processamento, senhor. Detalhes: {e}")

print("Jarvis Bot Universal (Sandbox + Banco + Conhecimento Geral) Online!")
bot.polling()