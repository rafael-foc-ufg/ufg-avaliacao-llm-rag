from django.core.management.base import BaseCommand

from painel.models import Questao, Rodada, registrar_execucao
from src.rag.cadeia import Cadeia, Direto


class Command(BaseCommand):
    help = "Responde as questoes do gabarito com e sem RAG e grava as execucoes na rodada"

    def add_arguments(self, parser):
        parser.add_argument("rodada", type=int)
        parser.add_argument("--questoes", type=int, nargs="+", help="pks das questoes; sem a opcao, todas")

    def handle(self, *args, **opcoes):
        rodada = Rodada.objects.select_related("indice").get(pk=opcoes["rodada"])
        aplicada = rodada.config
        try:
            sistemas = ((rodada.indice, Cadeia(aplicada)), (None, Direto(aplicada)))
            questoes = Questao.objects.all()
            if opcoes["questoes"]:
                questoes = questoes.filter(pk__in=opcoes["questoes"])
            for questao in questoes:
                for indice, sistema in sistemas:
                    resposta = sistema.responder(questao.pergunta)
                    registrar_execucao(
                        resposta, questao.pergunta, indice, aplicada, rodada=rodada, questao=questao
                    )
                    self.stdout.write(f"{questao.codigo} {'com' if indice else 'sem'} rag ok")
            rodada.status = Rodada.Status.CONCLUIDA
        except Exception as erro:
            rodada.status = Rodada.Status.FALHOU
            rodada.erro = descrever_erro(erro)
        rodada.save()


def descrever_erro(erro: BaseException) -> str:
    """Mensagem do erro seguida das causas encadeadas; "Connection error." sozinho nao diz o motivo."""
    partes = [f"{type(erro).__name__}: {erro}"]
    causa = erro.__cause__ or erro.__context__
    while causa is not None:
        partes.append(f"causa: {type(causa).__name__}: {causa}")
        causa = causa.__cause__ or causa.__context__
    return " | ".join(partes)
