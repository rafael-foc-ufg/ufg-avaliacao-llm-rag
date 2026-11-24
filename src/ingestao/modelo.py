import re
from dataclasses import dataclass


@dataclass
class Documento:
    doc_id: str
    fonte: str
    titulo: str
    texto: str
    meta: dict


ORDINAIS_TRIBUNAL = {
    "PRIMEIRA": "TRF-1",
    "SEGUNDA": "TRF-2",
    "TERCEIRA": "TRF-3",
    "QUARTA": "TRF-4",
}


DIGITOS_PROCESSO = 20
MINIMO_PARA_COMPLETAR_ZEROS = 16


def formatar_processo(digitos: str) -> str:
    """Completa zeros a esquerda perdidos na origem: parte dos CSVs do CJF traz o
    numero CNJ tipado como inteiro, sem os zeros iniciais."""
    limpo = re.sub(r"\D", "", digitos or "")
    if MINIMO_PARA_COMPLETAR_ZEROS <= len(limpo) < DIGITOS_PROCESSO:
        limpo = limpo.zfill(DIGITOS_PROCESSO)
    if len(limpo) != DIGITOS_PROCESSO:
        return digitos
    return f"{limpo[:7]}-{limpo[7:9]}.{limpo[9:13]}.{limpo[13]}.{limpo[14:16]}.{limpo[16:]}"


def sigla_tribunal(bruto: str) -> str:
    maiusculo = (bruto or "").upper()
    for ordinal, sigla in ORDINAIS_TRIBUNAL.items():
        if ordinal in maiusculo:
            return sigla
    return "TRF nao identificado"


def sigla_classe(bruto: str) -> str:
    texto = (bruto or "").strip()
    marcador = re.search(r"SIGLA_CLASSE:\s*(\S+)", texto)
    if marcador:
        return marcador.group(1)
    parenteses = re.search(r"\(([^)]+)\)\s*$", texto)
    if parenteses:
        return parenteses.group(1).strip()
    prefixo = re.match(r"([A-Za-z]{2,12})\s+-\s+", texto)
    if prefixo:
        return prefixo.group(1)
    return texto


def montar_citacao(meta: dict) -> str:
    data = meta["data_publicacao"]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", data):
        data = f"{data[8:]}/{data[5:7]}/{data[:4]}"
    return f"{meta['tribunal']}, {meta['classe']} {meta['processo']}, {data}"
