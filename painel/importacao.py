import re
import zipfile
from collections import Counter
from typing import BinaryIO
from xml.etree import ElementTree

from src.ingestao.cjf import sem_acento

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
LIMITE_XML = 50 * 1024 * 1024

CABECALHO_QUESTAO = re.compile(r"^Quest[aã]o\s+(\d+)\s*[–—-]\s*(.+)$")

SECOES_SEM_ACENTO = (
    ("pergunta", re.compile(r"^pergunta\s*:")),
    ("resposta_esperada", re.compile(r"^resposta esperada\s*:")),
    ("ementas_esperadas", re.compile(r"^(modelos? de )?ementas? esperadas?\s*:")),
    ("referencias", re.compile(r"^referencias?\s*:")),
    ("pontos_obrigatorios", re.compile(r"^pontos obrigatorios\b")),
    ("inaceitavel", re.compile(r"^inaceitave(l|is)\s*:")),
    ("observacao", re.compile(r"^observac(ao|oes)\s*:")),
)
CAMPOS_DE_TEXTO = ("pergunta", "resposta_esperada", "observacao")
CAMPOS_DE_LISTA = ("ementas_esperadas", "referencias", "pontos_obrigatorios", "inaceitavel")
MARCADOR_VERSAO = re.compile(r"\[NOVO[^\]]*\]", re.IGNORECASE)
SENTIMENTO = re.compile(r"\b(positivo|negativo)\b", re.IGNORECASE)


class ErroImportacao(Exception):
    pass


def paragrafos(arquivo: BinaryIO) -> list[str]:
    """Texto de cada paragrafo do corpo, na ordem; quebra manual (Shift+Enter) abre outro paragrafo."""
    try:
        with zipfile.ZipFile(arquivo) as pacote:
            info = pacote.getinfo("word/document.xml")
            if info.file_size > LIMITE_XML:
                raise ErroImportacao("O documento é grande demais para importar.")
            raiz = ElementTree.fromstring(pacote.read(info))
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as erro:
        raise ErroImportacao("O arquivo não é um documento Word (.docx) válido.") from erro
    textos = []
    for paragrafo in raiz.iter(f"{W}p"):
        linhas = [[]]
        for elemento in paragrafo.iter():
            if elemento.tag == f"{W}t":
                linhas[-1].append(elemento.text or "")
            elif elemento.tag == f"{W}tab":
                linhas[-1].append(" ")
            elif elemento.tag == f"{W}br":
                linhas.append([])
        for partes in linhas:
            texto = " ".join("".join(partes).split())
            if texto:
                textos.append(texto)
    return textos


def secao_do_rotulo(texto: str) -> tuple[str, str] | None:
    """Se o paragrafo abre uma secao, devolve o campo e o texto que vem depois do rotulo."""
    normalizado = sem_acento(texto).lower()
    for campo, padrao in SECOES_SEM_ACENTO:
        if padrao.match(normalizado):
            resto = texto.split(":", 1)[1] if ":" in texto else ""
            return campo, MARCADOR_VERSAO.sub("", resto).strip()
    return None


def limpar_item(texto: str) -> str:
    return texto.strip().rstrip(";,:").strip()


def nova_questao(numero: int, titulo: str) -> dict:
    return {
        "codigo": f"Q{numero:02d}",
        "numero": numero,
        "titulo": titulo.strip(),
        "sentimento_esperado": "",
        **{campo: [] for campo in CAMPOS_DE_TEXTO},
        **{campo: [] for campo in CAMPOS_DE_LISTA},
        "avisos": [],
        "erros": [],
    }


def registrar_sentimento(questao: dict, texto: str) -> None:
    encontrados = [s.lower() for s in SENTIMENTO.findall(texto)]
    if not encontrados:
        return
    if questao["sentimento_esperado"]:
        questao["avisos"].append("Mais de uma frase de sentimento; foi usada a primeira.")
        return
    if len(set(encontrados)) > 1:
        questao["sentimento_esperado"] = "positivo_ou_negativo"
        questao["avisos"].append("O sentimento cita positivo e negativo; foi usado \"positivo ou negativo\".")
    else:
        questao["sentimento_esperado"] = encontrados[0]


def finalizar(questao: dict) -> dict:
    for campo in CAMPOS_DE_TEXTO:
        questao[campo] = "\n\n".join(questao[campo])
    if len(questao["titulo"]) > 200:
        questao["erros"].append("O título passa de 200 caracteres.")
    for campo, rotulo in (("pergunta", "a pergunta"), ("resposta_esperada", "a resposta esperada")):
        if not questao[campo]:
            questao["erros"].append(f"Não foi encontrada {rotulo}.")
    if not questao["sentimento_esperado"]:
        questao["erros"].append("Não foi encontrado o sentimento esperado (positivo, negativo ou os dois).")
    if not questao["ementas_esperadas"]:
        questao["avisos"].append("Nenhuma ementa esperada.")
    return questao


def ler_mapeamento(arquivo: BinaryIO) -> list[dict]:
    """Converte o documento em questoes no formato do gabarito, com avisos e erros por questao."""
    questoes: list[dict] = []
    atual: dict | None = None
    secao: str | None = None
    for texto in paragrafos(arquivo):
        cabecalho = CABECALHO_QUESTAO.match(texto)
        if cabecalho:
            if atual:
                questoes.append(finalizar(atual))
            atual, secao = nova_questao(int(cabecalho.group(1)), cabecalho.group(2)), None
            continue
        if atual is None:
            continue
        rotulo = secao_do_rotulo(texto)
        if rotulo:
            secao, texto = rotulo
            if not texto:
                continue
        if secao is None:
            atual["avisos"].append(f"Texto fora de seção ignorado: {texto[:80]}")
            continue
        if secao == "resposta_esperada" and sem_acento(texto).lower().startswith("o sentimento"):
            registrar_sentimento(atual, texto)
        if secao in CAMPOS_DE_LISTA:
            item = limpar_item(texto)
            if item:
                atual[secao].append(item)
        else:
            atual[secao].append(texto.strip())
    if atual:
        questoes.append(finalizar(atual))
    if not questoes:
        raise ErroImportacao("Nenhuma questão encontrada. Os títulos devem seguir o formato \"Questão 01 – Tema\".")
    repeticoes = Counter(questao["numero"] for questao in questoes)
    for questao in questoes:
        if repeticoes[questao["numero"]] > 1:
            questao["erros"].append(f"O número {questao['numero']} aparece mais de uma vez no documento.")
    return questoes
