import random

from django.conf import settings
from django.core.management.base import BaseCommand

from painel.models import Avaliacao, Rodada, reverificar_processos
from src.avaliacao.juiz import Juiz
from src.configuracao import carregar_config


class Command(BaseCommand):
    help = (
        "Avalia com o modelo juiz, as cegas e em ordem aleatoria, as respostas ainda nao avaliadas da rodada; "
        "no fim, reconsulta os processos que ficaram sem verificacao no DataJud"
    )

    def add_arguments(self, parser):
        parser.add_argument("rodada", type=int)
        parser.add_argument("--novo", action="store_true", help="abre um novo julgamento e reavalia todas as respostas")
        parser.add_argument(
            "--questoes", type=int, nargs="+", help="pks das questoes cuja avaliacao no julgamento atual e refeita"
        )

    def handle(self, *args, **opcoes):
        rodada = Rodada.objects.get(pk=opcoes["rodada"])
        julgamentos = rodada.julgamentos()
        julgamento = max(julgamentos, default=0) + 1 if opcoes["novo"] else max(julgamentos, default=1)
        try:
            config = carregar_config(settings.RAG_CONFIG)
            juiz = Juiz(config)
            execucoes = rodada.execucoes.filter(questao__isnull=False)
            if opcoes["questoes"]:
                execucoes = execucoes.filter(questao__in=opcoes["questoes"])
                Avaliacao.objects.filter(execucao__in=execucoes, julgamento=julgamento).delete()
            pendentes = list(execucoes.exclude(avaliacoes__julgamento=julgamento).select_related("questao"))
            random.shuffle(pendentes)
            for numero, execucao in enumerate(pendentes, start=1):
                gabarito = execucao.questao.como_gabarito()
                julgado = juiz.avaliar(gabarito, execucao.resposta)
                avaliacao = Avaliacao(
                    execucao=execucao,
                    julgamento=julgamento,
                    modelo=juiz.modelo,
                    prompt=juiz.prompt,
                    gabarito=gabarito,
                    vereditos=[v.model_dump() for v in julgado.vereditos],
                    latencia_ms=julgado.latencia_ms,
                    tokens_entrada=julgado.tokens_entrada,
                    tokens_saida=julgado.tokens_saida,
                    processos=julgado.processos,
                )
                avaliacao.pontuar()
                avaliacao.save()
                self.stdout.write(f"julgamento {julgamento}: avaliada {numero} de {len(pendentes)}")
            restantes = reverificar_processos(rodada, config)
            self.stdout.write(f"processos ainda nao verificados: {restantes}")
            rodada.status_avaliacao = Rodada.StatusAvaliacao.CONCLUIDA
        except Exception as erro:
            rodada.status_avaliacao = Rodada.StatusAvaliacao.FALHOU
            rodada.erro_avaliacao = str(erro)
        rodada.save()
