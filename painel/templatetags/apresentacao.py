import re

from bs4 import BeautifulSoup
from django import template
from django.template.defaultfilters import floatformat
from django.utils.html import format_html_join
from django.utils.safestring import SafeString, mark_safe
from django.utils.text import Truncator
from markdown_it import MarkdownIt

from painel.forms import FONTES
from src.ingestao.legislacao import MARCA_REVOGADO

TAMANHO_PREVIA = 70
LIMITE_DIVERGENCIA = 0.3
LIMITE_TINTA_CLARA = 0.6
CABECALHO_DE_NUMERACAO = re.compile(r"#|N[º°o]\.?|Item", re.IGNORECASE)

SITUACOES = {
    "confirmada": "Confirmada",
    "contradita": "Contradita",
    "nao_verificavel": "Não verificável",
    "correta": "Correta",
    "incorreta": "Incorreta",
    "presente": "Presente",
    "faltou": "Faltou",
}

register = template.Library()

conversor_markdown = MarkdownIt("commonmark", {"html": False}).enable("table")


@register.filter
def markdown(texto: str) -> SafeString:
    """HTML vindo do modelo sai escapado, pois o conversor roda com html desligado."""
    return mark_safe(marcar_tabelas_numeradas(conversor_markdown.render(texto)))


def marcar_tabelas_numeradas(html: str) -> str:
    """Tabela cuja primeira coluna e so numeracao (#, No, Item) ganha a classe numerada, que o CSS estreita."""
    sopa = BeautifulSoup(html, "html.parser")
    for tabela in sopa.find_all("table"):
        primeira = tabela.find("th")
        if primeira and CABECALHO_DE_NUMERACAO.fullmatch(primeira.get_text(strip=True)):
            tabela["class"] = "numerada"
    return str(sopa)


@register.filter
def texto_legal(texto: str) -> SafeString:
    """Cada linha vira um paragrafo; o que vem depois de [REVOGADO] sai riscado."""
    linhas = [linha.partition(MARCA_REVOGADO) for linha in texto.splitlines() if linha.strip()]
    return format_html_join("", "<p>{}<s>{}</s></p>", ((vigente, revogado) for vigente, _, revogado in linhas))


@register.filter
def previa(texto: str) -> str:
    return Truncator(texto.replace(MARCA_REVOGADO, "").strip()).chars(TAMANHO_PREVIA)


@register.filter
def segundos(milissegundos: int) -> str:
    return f"{floatformat(milissegundos / 1000, 1)} s"


@register.filter
def nome_fonte(fonte: str) -> str:
    return dict(FONTES).get(fonte, fonte)


@register.filter
def situacao_item(situacao: str) -> str:
    return SITUACOES[situacao]


@register.filter
def divergiu(valores: list[float | None]) -> bool:
    validos = [valor for valor in valores if valor is not None]
    return len(validos) > 1 and max(validos) - min(validos) >= LIMITE_DIVERGENCIA


@register.filter
def cor_mapa(valor: float | None, escala: int = 1) -> str:
    """Estilo da celula do mapa: quanto maior o valor na escala, mais escuro o fundo."""
    if valor is None:
        return ""
    proporcao = valor / escala
    tinta = "#fff" if proporcao >= LIMITE_TINTA_CLARA else "var(--tinta)"
    return f"background: color-mix(in oklab, var(--teal) {round(proporcao * 100)}%, var(--fundo)); color: {tinta}"
