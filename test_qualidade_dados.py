"""Testes da camada de qualidade. Execute: python -m unittest -v"""
import logging
import sqlite3
import tempfile
import unittest
from pathlib import Path

from qualidade_dados import (
    corrigir_texto, validar_data, validar_numero,
    tratar_registro, sanitizar_linhas_consulta
)

logging.disable(logging.CRITICAL)


class TestTexto(unittest.TestCase):
    def test_mojibake_simples(self):
        self.assertEqual(corrigir_texto("OperaÃ§Ã£o")[0], "Operação")

    def test_mojibake_duas_camadas(self):
        texto = "Jurídico".encode().decode("latin-1").encode().decode("latin-1")
        self.assertEqual(corrigir_texto(texto)[0], "Jurídico")

    def test_texto_legitimo_com_til_nao_e_alterado(self):
        self.assertEqual(corrigir_texto("ÃREA")[0], "ÃREA")
        self.assertEqual(corrigir_texto("Operação")[0], "Operação")

    def test_latin1_em_bytes(self):
        texto, probs = corrigir_texto(b"Comunica\xe7\xe3o")
        self.assertEqual(texto, "Comunicação")
        self.assertIn("bytes_decodificados_cp1252", probs)

    def test_bytes_irrecuperaveis_sinalizados(self):
        _, probs = corrigir_texto(b"Finan\xe7eiro\x81")
        self.assertIn("bytes_utf8_invalidos", probs)

    def test_nulo_vazio_e_espacos(self):
        self.assertEqual(corrigir_texto(None), (None, ["texto_nulo"]))
        self.assertIsNone(corrigir_texto("")[0])
        self.assertIsNone(corrigir_texto("   ")[0])

    def test_controle_e_espacos(self):
        self.assertEqual(corrigir_texto("  Ven\x00das   Sul ")[0], "Vendas Sul")


class TestData(unittest.TestCase):
    def test_validas(self):
        self.assertEqual(validar_data("2026-01-01"), ("2026-01-01", []))

    def test_formatos_convertidos(self):
        for entrada in ("15/05/2026", "2026/05/15", "2026-05-15T10:30:00"):
            data, avisos = validar_data(entrada)
            self.assertEqual(data, "2026-05-15", entrada)
            self.assertIn("data_formato_convertido", avisos)

    def test_invalidas(self):
        for entrada in ("2026-15-45", "0000-00-00", "2026-02-30", "ontem", "31/02/2026"):
            self.assertIsNone(validar_data(entrada)[0], entrada)

    def test_ausentes_e_fora_do_intervalo(self):
        self.assertEqual(validar_data(None)[1], ["data_ausente"])
        self.assertEqual(validar_data("1850-01-01")[1], ["data_fora_do_intervalo"])


class TestNumero(unittest.TestCase):
    def test_validos(self):
        self.assertEqual(validar_numero(10)[0], 10.0)
        self.assertEqual(validar_numero("1234.5")[0], 1234.5)

    def test_formato_brasileiro(self):
        self.assertEqual(validar_numero("R$ 15.250,75")[0], 15250.75)
        self.assertEqual(validar_numero("1.234.567")[0], 1234567.0)
        self.assertEqual(validar_numero("1,234.56")[0], 1234.56)

    def test_rejeicoes(self):
        for entrada in ("muitos", "indefinida", "1,2,3", "1_000", True, float("inf"),
                        float("nan"), "nan", "inf"):
            self.assertIsNone(validar_numero(entrada)[0], entrada)
        self.assertEqual(validar_numero(None)[1], ["valor_ausente"])
        self.assertEqual(validar_numero("")[1], ["valor_ausente"])


class TestSanitizacaoConsulta(unittest.TestCase):
    def test_linhas_com_mojibake_e_valores_invalidos(self):
        linhas_brutas = [
            {"loja": "Loja Centro", "metrica": "Faturamento", "valor": 120000.0},
            {"loja": "OperaÃ§Ã£o_Quebrada", "metrica": "Faturamento", "valor": 45000.0},
            {"loja": "Loja Negativa", "metrica": "Faturamento", "valor": -999.0},
            {"loja": "Loja Estorno", "metrica": "Estorno", "valor": -3500.0},
            {"loja": b"Finan\xe7eiro\x81", "metrica": "Receita", "valor": 50000.0}
        ]
        limpos, isolados = sanitizar_linhas_consulta(linhas_brutas)
        self.assertEqual(len(limpos), 3)
        self.assertEqual(isolados, 2)
        self.assertEqual(limpos[1]["loja"], "Operação_Quebrada")
        self.assertEqual(limpos[2]["valor"], -3500.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
    
