from pathlib import Path

from django.core.management.base import BaseCommand

from painel.exportacao import gravar_planilha
from painel.models import Rodada


class Command(BaseCommand):
    help = "Exporta as respostas avaliadas das rodadas para um xlsx, uma linha por resposta"

    def add_arguments(self, parser):
        parser.add_argument("--arquivo", default="data/rodadas.xlsx")

    def handle(self, *args, **opcoes):
        arquivo = Path(opcoes["arquivo"])
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        total = gravar_planilha(arquivo, Rodada.objects.all())
        self.stdout.write(f"{total} avaliacoes exportadas para {arquivo}")
