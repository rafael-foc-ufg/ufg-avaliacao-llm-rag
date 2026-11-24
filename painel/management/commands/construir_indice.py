from functools import partial

from django.conf import settings
from django.core.management.base import BaseCommand

from painel.models import Indice, medir_chunks
from src.configuracao import carregar_config
from src.ingestao.construir_indice import COLECOES, construir


def registrar_progresso(
    indice: Indice, fonte: str, etapa: str, feitos: int, total: int, documento: str
) -> None:
    indice.progresso = {
        "fonte": fonte,
        "etapa": etapa,
        "feitos": feitos,
        "total": total,
        "percentual": feitos * 100 // total,
        "documento": documento,
    }
    indice.save(update_fields=["progresso"])


class Command(BaseCommand):
    help = "Constroi em pasta propria o indice registrado no banco"

    def add_arguments(self, parser):
        parser.add_argument("nome")

    def handle(self, *args, **opcoes):
        indice = Indice.objects.get(nome=opcoes["nome"])
        config = carregar_config(settings.RAG_CONFIG)
        aplicada = indice.config_aplicada(config)
        try:
            indice.pasta(config).mkdir(parents=True)
            for posicao, fonte in enumerate(COLECOES, start=1):
                etapa = f"{posicao} de {len(COLECOES)}"
                construir(
                    aplicada,
                    fonte,
                    limite=indice.limite,
                    ao_avancar=partial(registrar_progresso, indice, fonte, etapa),
                )
            indice.estatisticas = medir_chunks(aplicada, indice.limite)
            indice.status = Indice.Status.PRONTO
        except Exception as erro:
            indice.status = Indice.Status.FALHOU
            indice.erro = str(erro)
        indice.save()
