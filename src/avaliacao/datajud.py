import os
import re
from functools import cache

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

PADRAO_CNJ = re.compile(r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b")
TRACOS_PARA_HIFEN = str.maketrans(dict.fromkeys("‐‑‒–—−", "-"))


class ConsultaIncompleta(Exception):
    pass


def extrair_numeros_cnj(texto: str) -> list[str]:
    """Aceita o numero escrito com hifen inseparavel (U+2011) ou outro traco, comum na saida dos modelos."""
    return list(dict.fromkeys(PADRAO_CNJ.findall(texto.translate(TRACOS_PARA_HIFEN))))


def digito_valido(digitos: str) -> bool:
    """Digito verificador modulo 97 da Resolucao CNJ 65/2008, sobre os 20 digitos."""
    return 98 - int(digitos[:7] + digitos[9:] + "00") % 97 == int(digitos[7:9])


def alias_tribunal(digitos: str) -> str | None:
    segmento, tribunal = digitos[13], int(digitos[14:16])
    if segmento == "4":
        return f"trf{tribunal}"
    if segmento == "3":
        return "stj"
    return None


@cache
@retry(
    retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout, ConsultaIncompleta)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=2, max=30),
    reraise=True,
)
def consultar_datajud(url: str, alias: str, digitos: str) -> bool:
    """Shard falho com zero resultados nao prova inexistencia; vira ConsultaIncompleta."""
    resposta = requests.post(
        f"{url}/api_publica_{alias}/_search",
        headers={"Authorization": f"APIKey {os.environ['DATAJUD_API_KEY']}"},
        json={"query": {"match": {"numeroProcesso": digitos}}, "size": 0},
        timeout=90,
    )
    if resposta.status_code >= 500:
        raise ConsultaIncompleta(f"{alias}: HTTP {resposta.status_code}")
    resposta.raise_for_status()
    corpo = resposta.json()
    encontrados = corpo["hits"]["total"]["value"]
    if not encontrados and corpo["_shards"]["failed"]:
        raise ConsultaIncompleta(f"{alias}: {corpo['_shards']['failed']} shards falharam")
    return encontrados > 0


def verificar_processos(texto: str, url: str, na_base: frozenset[str]) -> dict[str, str]:
    """Cada numero CNJ citado vira existe, inexistente ou nao_verificado; falha do DataJud nunca para a avaliacao.
    na_base traz os digitos dos processos da base local, que existem sem precisar consultar o DataJud."""
    situacoes = {}
    for numero in extrair_numeros_cnj(texto):
        digitos = re.sub(r"\D", "", numero)
        alias = alias_tribunal(digitos)
        if not digito_valido(digitos):
            situacoes[numero] = "inexistente"
        elif digitos in na_base:
            situacoes[numero] = "existe"
        elif alias is None or not os.environ.get("DATAJUD_API_KEY"):
            situacoes[numero] = "nao_verificado"
        else:
            try:
                situacoes[numero] = "existe" if consultar_datajud(url, alias, digitos) else "inexistente"
            except (requests.RequestException, ConsultaIncompleta):
                situacoes[numero] = "nao_verificado"
    return situacoes
