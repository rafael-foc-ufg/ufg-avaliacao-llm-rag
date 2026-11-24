import json
from pathlib import Path

from django.core.management.base import BaseCommand

from painel.models import Questao

CAMPOS = (
    "numero",
    "titulo",
    "pergunta",
    "resposta_esperada",
    "sentimento_esperado",
    "ementas_esperadas",
    "referencias",
    "pontos_obrigatorios",
    "inaceitavel",
    "observacao",
)


class Command(BaseCommand):
    help = "Importa as questoes do gabarito JSON; questoes com o mesmo codigo sao atualizadas"

    def add_arguments(self, parser):
        parser.add_argument("--arquivo", default="docs/gabarito.json")

    def handle(self, *args, **opcoes):
        gabarito = json.loads(Path(opcoes["arquivo"]).read_text(encoding="utf-8"))
        for questao in gabarito["questoes"]:
            valores = {campo: questao[campo] for campo in CAMPOS if campo in questao}
            _, criada = Questao.objects.update_or_create(codigo=questao["id"], defaults=valores)
            self.stdout.write(f"{questao['id']} {'criada' if criada else 'atualizada'}")
