from collections import Counter
from io import BytesIO
import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.db import transaction
from django.db.models import Count, Max
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView
from django.views.decorators.http import require_POST
from langchain_chroma import Chroma

from painel.exportacao import gravar_planilha
from painel.fichas import fichas_com_config
from painel.importacao import CAMPOS_DE_LISTA, CAMPOS_DE_TEXTO, ErroImportacao, ler_mapeamento
from painel.forms import (
    AjustesForm,
    BuscaForm,
    ColunaForm,
    CredenciaisForm,
    FiltroChunksForm,
    ImportarGabaritoForm,
    JuizForm,
    NovoIndiceForm,
    PerguntaForm,
    QuestaoForm,
    RodadaForm,
    ajustes_do_config,
    aplicar_ajustes,
)
from painel.models import (
    Avaliacao,
    Execucao,
    Indice,
    Questao,
    Rodada,
    SISTEMAS,
    delta_verificado,
    gerar_nome,
    medir_chunks,
    placar,
    registrar_execucao,
)
from src.avaliacao.juiz import carregar_prompt
from src.configuracao import carregar_config, salvar_config, salvar_credencial
from src.ingestao.construir_indice import COLECOES
from src.rag.cadeia import Cadeia, Direto
from src.rag.llm import listar_modelos_groq
from src.rag.recuperador import Recuperador, aplicar_piso
from src.testar_modelo import TESTES_POR_CHAVE, chaves_em_uso, diagnosticar, escolher_teste

CHUNKS_POR_PAGINA = 50
EXECUCOES_NO_INICIO = 5
AJUSTES_SEMPRE_VISIVEIS = ("ativa", "com_rag", "indice", "temperatura")


def inicio(request: HttpRequest) -> HttpResponse:
    execucoes = Execucao.objects.select_related("indice")[:EXECUCOES_NO_INICIO]
    return render(request, "painel/inicio.html", {"execucoes": execucoes})


def contexto_configuracoes(formulario: AjustesForm, **extras) -> dict:
    return {
        "formulario": formulario,
        "credenciais": CredenciaisForm(),
        "groq_configurado": bool(os.environ.get("GROQ_API_KEY")),
        "modelos_groq": listar_modelos_groq(),
        **extras,
    }


def configuracoes(request: HttpRequest) -> HttpResponse:
    config = carregar_config(settings.RAG_CONFIG)
    formulario = AjustesForm(request.POST or None, initial=ajustes_do_config(config))
    if formulario.is_valid():
        salvar_config(aplicar_ajustes(config, formulario.cleaned_data), settings.RAG_CONFIG)
        messages.success(request, "Configurações salvas.")
        return redirect("configuracoes")
    return render(request, "painel/configuracoes.html", contexto_configuracoes(formulario))


@require_POST
def salvar_credenciais(request: HttpRequest) -> HttpResponse:
    formulario = CredenciaisForm(request.POST)
    if formulario.is_valid():
        salvar_credencial("GROQ_API_KEY", formulario.cleaned_data["groq_api_key"].strip(), settings.ARQUIVO_ENV)
        messages.success(request, "Chave do Groq salva.")
    else:
        messages.error(request, "Informe a chave do Groq.")
    return redirect("configuracoes")


def juiz(request: HttpRequest) -> HttpResponse:
    config = carregar_config(settings.RAG_CONFIG)
    inicial = {
        "modelo": config["modelos"]["juiz"],
        "modelo_groq": config["modelos"]["juiz_groq"],
        "raciocinio_groq": config["geracao"]["raciocinio_juiz_groq"],
        "prompt": carregar_prompt(config),
    }
    formulario = JuizForm(request.POST or None, initial=inicial)
    if formulario.is_valid():
        Path(config["caminhos"]["prompt_juiz"]).write_text(formulario.cleaned_data["prompt"] + "\n", encoding="utf-8")
        config["modelos"]["juiz"] = formulario.cleaned_data["modelo"]
        config["modelos"]["juiz_groq"] = formulario.cleaned_data["modelo_groq"]
        config["geracao"]["raciocinio_juiz_groq"] = formulario.cleaned_data["raciocinio_groq"]
        salvar_config(config, settings.RAG_CONFIG)
        messages.success(request, "Configuração do juiz salva.")
        return redirect("juiz")
    return render(
        request,
        "painel/juiz.html",
        {
            "formulario": formulario,
            "caminho": config["caminhos"]["prompt_juiz"],
            "provedor": config["provedor"],
            "modelos_groq": listar_modelos_groq(),
        },
    )


def modelos(request: HttpRequest) -> HttpResponse:
    config = carregar_config(settings.RAG_CONFIG)
    return render(
        request,
        "painel/modelos.html",
        {"fichas": fichas_com_config(config), "regiao": config["modelos"]["regiao"]},
    )


@require_POST
def testar_modelos(request: HttpRequest) -> HttpResponse:
    config = carregar_config(settings.RAG_CONFIG)
    regiao = config["modelos"]["regiao"]
    resultados = []
    for chave in chaves_em_uso(config):
        modelo = config["modelos"][chave]
        teste = TESTES_POR_CHAVE.get(chave) or escolher_teste(modelo)
        try:
            teste(modelo, regiao)
            resultados.append({"modelo": modelo, "diagnostico": "acesso confirmado"})
        except Exception as erro:
            resultados.append({"modelo": modelo, "diagnostico": diagnosticar(erro)})
    formulario = AjustesForm(initial=ajustes_do_config(config))
    return render(request, "painel/configuracoes.html", contexto_configuracoes(formulario, resultados=resultados))


def indices(request: HttpRequest) -> HttpResponse:
    todos = Indice.objects.all()
    construindo = any(indice.status == Indice.Status.CONSTRUINDO for indice in todos)
    indice_ativo = Path(carregar_config(settings.RAG_CONFIG)["caminhos"]["indice"]).name
    return render(
        request,
        "painel/indices.html",
        {"indices": todos, "construindo": construindo, "indice_ativo": indice_ativo},
    )


def novo_indice(request: HttpRequest) -> HttpResponse:
    config = carregar_config(settings.RAG_CONFIG)
    if request.method == "GET":
        formulario = NovoIndiceForm(
            initial={
                "prefixo": "indice",
                "tamanho": config["chunking"]["tamanho"],
                "overlap": config["chunking"]["overlap"],
                "embedding": config["modelos"]["embedding"],
            }
        )
        return render(request, "painel/novo_indice.html", {"formulario": formulario})

    formulario = NovoIndiceForm(request.POST)
    if not formulario.is_valid():
        return render(request, "painel/novo_indice.html", {"formulario": formulario})

    dados = formulario.cleaned_data
    parametros = {campo: dados[campo] for campo in ("tamanho", "overlap", "embedding", "limite")}

    if request.POST.get("acao") == "construir":
        nome = gerar_nome(dados["prefixo"], timezone.localtime(timezone.now()))
        if Indice.objects.filter(nome=nome).exists():
            formulario.add_error(None, "Já existe um índice com este nome. Aguarde um minuto ou use outro prefixo.")
            return render(request, "painel/novo_indice.html", {"formulario": formulario})
        Indice.objects.create(nome=nome, **parametros)
        subprocess.Popen([sys.executable, "manage.py", "construir_indice", nome], cwd=settings.BASE_DIR)
        return redirect("indices")

    medidas = medir_chunks(Indice(**parametros).config_aplicada(config), dados["limite"])
    estimativa = [
        {
            "fonte": fonte,
            "chunks": medida["chunks"],
            "caracteres": medida["caracteres"],
            "tokens_min": medida["caracteres"] // 4,
            "tokens_max": medida["caracteres"] // 3,
        }
        for fonte, medida in medidas.items()
    ]
    return render(
        request,
        "painel/novo_indice.html",
        {
            "formulario": formulario,
            "estimativa": estimativa,
            "estimado": NovoIndiceForm(request.POST, auto_id=False),
        },
    )


def indice(request: HttpRequest, nome: str) -> HttpResponse:
    registro = get_object_or_404(Indice, nome=nome)
    config = carregar_config(settings.RAG_CONFIG)
    pasta = registro.pasta(config)
    filtro = FiltroChunksForm(request.GET)
    dados = filtro.cleaned_data if filtro.is_valid() else {}
    pagina = dados.get("pagina") or 1
    doc_id = dados.get("doc_id")
    fonte = dados.get("fonte") or "cjf"

    pronto = registro.status == Indice.Status.PRONTO
    chunks = []
    if pronto and pasta.exists():
        colecao = Chroma(collection_name=COLECOES[fonte], persist_directory=str(pasta))
        lidos = colecao.get(
            limit=CHUNKS_POR_PAGINA,
            offset=(pagina - 1) * CHUNKS_POR_PAGINA,
            where={"doc_id": doc_id} if doc_id else None,
            include=["documents", "metadatas"],
        )
        chunks = [
            {"texto": texto, "meta": meta} for texto, meta in zip(lidos["documents"], lidos["metadatas"])
        ]

    return render(
        request,
        "painel/indice.html",
        {
            "indice": registro,
            "indice_ativo": Path(config["caminhos"]["indice"]).name,
            "filtro": filtro,
            "chunks": chunks,
            "pasta_ausente": pronto and not pasta.exists(),
            "primeiro_chunk": (pagina - 1) * CHUNKS_POR_PAGINA + 1,
            "ultimo_chunk": (pagina - 1) * CHUNKS_POR_PAGINA + len(chunks),
            "total_da_fonte": None if doc_id else registro.estatisticas.get(fonte, {}).get("chunks"),
            "pagina_anterior": pagina - 1,
            "pagina_seguinte": pagina + 1 if len(chunks) == CHUNKS_POR_PAGINA else None,
        },
    )


@require_POST
def ativar_indice(request: HttpRequest, nome: str) -> HttpResponse:
    registro = get_object_or_404(Indice, nome=nome, status=Indice.Status.PRONTO)
    config = carregar_config(settings.RAG_CONFIG)
    config["caminhos"]["indice"] = registro.pasta(config).as_posix()
    config["modelos"]["embedding"] = registro.embedding
    salvar_config(config, settings.RAG_CONFIG)
    messages.success(request, f"Índice {registro.nome} ativado.")
    return redirect("indices")


def busca(request: HttpRequest) -> HttpResponse:
    contexto = {"sem_indice": not Indice.objects.filter(status=Indice.Status.PRONTO).exists()}
    formulario = BuscaForm(request.POST or None)
    contexto["formulario"] = formulario
    if formulario.is_valid():
        config = carregar_config(settings.RAG_CONFIG)
        aplicada = formulario.cleaned_data["indice"].config_aplicada(config)
        try:
            ordenados = Recuperador(aplicada).ordenar(formulario.cleaned_data["pergunta"])
        except Exception as erro:
            contexto["erro"] = diagnosticar(erro)
        else:
            escolhidos = aplicar_piso(
                ordenados, aplicada["recuperacao"]["top_k"], aplicada["recuperacao"]["piso_por_fonte"]
            )
            contexto["linhas"] = [
                {"trecho": trecho, "escolhido": trecho in escolhidos} for trecho in ordenados
            ]
            contexto["total_escolhidos"] = len(escolhidos)
    return render(request, "painel/busca.html", contexto)


def comparar(request: HttpRequest) -> HttpResponse:
    config = carregar_config(settings.RAG_CONFIG)
    inicial = ajustes_do_config(config)
    contexto = {"pergunta_form": PerguntaForm(request.POST or None)}
    colunas = []
    for prefixo in "abc":
        ativa = request.method == "POST" and f"{prefixo}-ativa" in request.POST
        formulario = ColunaForm(request.POST if ativa else None, prefix=prefixo, initial=inicial)
        colunas.append({"formulario": formulario, "ativa": ativa, "rotulo": prefixo.upper()})
    contexto["colunas"] = colunas
    contexto["ajustes"] = linhas_de_ajustes(colunas)

    if request.method == "POST":
        ativas = [coluna for coluna in colunas if coluna["ativa"]]
        if len(ativas) < 2:
            contexto["erro"] = "Selecione ao menos duas colunas."
        elif contexto["pergunta_form"].is_valid() and all(c["formulario"].is_valid() for c in ativas):
            pergunta = contexto["pergunta_form"].cleaned_data["pergunta"]
            for coluna in ativas:
                executar_coluna(coluna, pergunta, config)
    return render(request, "painel/comparar.html", contexto)


def linhas_de_ajustes(colunas: list[dict]) -> list[dict]:
    """Uma linha por ajuste, com o campo de cada coluna, para a tabela de comparacao."""
    demais = [nome for nome in colunas[0]["formulario"].fields if nome not in AJUSTES_SEMPRE_VISIVEIS]
    return [
        {
            "nome": nome,
            "rotulo": colunas[0]["formulario"][nome].label,
            "fixo": nome in AJUSTES_SEMPRE_VISIVEIS,
            "campos": [coluna["formulario"][nome] for coluna in colunas],
        }
        for nome in (*AJUSTES_SEMPRE_VISIVEIS, *demais)
    ]


def executar_coluna(coluna: dict, pergunta: str, config: dict) -> None:
    dados = coluna["formulario"].cleaned_data
    indice = dados["indice"] if dados["com_rag"] else None
    base = indice.config_aplicada(config) if indice else config
    aplicada = aplicar_ajustes(base, dados)
    try:
        executor = Cadeia(aplicada) if indice else Direto(aplicada)
        resposta = executor.responder(pergunta)
    except Exception as erro:
        coluna["erro"] = diagnosticar(erro)
        return
    registrar_execucao(resposta, pergunta, indice, aplicada)
    coluna["resposta"] = resposta


class HistoricoView(ListView):
    queryset = Execucao.objects.select_related("indice")
    paginate_by = 50


class ExecucaoView(DetailView):
    model = Execucao


class GabaritoView(ListView):
    model = Questao


class NovaQuestaoView(SuccessMessageMixin, CreateView):
    model = Questao
    form_class = QuestaoForm
    success_url = reverse_lazy("gabarito")
    success_message = "Questão %(codigo)s cadastrada."

    def get_initial(self):
        numero = (Questao.objects.aggregate(maior=Max("numero"))["maior"] or 0) + 1
        return {"numero": numero, "codigo": f"Q{numero:02d}"}


class EditarQuestaoView(SuccessMessageMixin, UpdateView):
    model = Questao
    form_class = QuestaoForm
    success_url = reverse_lazy("gabarito")
    success_message = "Questão %(codigo)s salva."


class ExcluirQuestaoView(SuccessMessageMixin, DeleteView):
    model = Questao
    success_url = reverse_lazy("gabarito")
    success_message = "Questão excluída."


CHAVE_IMPORTACAO = "importacao_gabarito"


def conferir_importacao(questoes: list[dict]) -> dict:
    """Marca em cada questao se ja existe e o conflito de numero com a base; devolve o resumo para a previa."""
    numeros_por_codigo = dict(Questao.objects.values_list("codigo", "numero"))
    codigos_por_numero = {numero: codigo for codigo, numero in numeros_por_codigo.items()}
    for questao in questoes:
        questao["existe"] = questao["codigo"] in numeros_por_codigo
        dono = codigos_por_numero.get(questao["numero"], questao["codigo"])
        questao["conflito"] = (
            f"O número {questao['numero']} já pertence à questão {dono}." if dono != questao["codigo"] else ""
        )
    existentes = [questao["codigo"] for questao in questoes if questao["existe"]]
    return {
        "questoes": questoes,
        "existentes": len(existentes),
        "novas": len(questoes) - len(existentes),
        "bloqueada": any(questao["erros"] or questao["conflito"] for questao in questoes),
        "execucoes_afetadas": Execucao.objects.filter(questao__codigo__in=existentes).count(),
    }


def importar_gabarito(request: HttpRequest) -> HttpResponse:
    formulario = ImportarGabaritoForm(request.POST or None, request.FILES or None)
    contexto = {"formulario": formulario}
    if request.method == "POST" and formulario.is_valid():
        arquivo = formulario.cleaned_data["arquivo"]
        try:
            questoes = ler_mapeamento(arquivo)
        except ErroImportacao as erro:
            formulario.add_error("arquivo", str(erro))
        else:
            request.session[CHAVE_IMPORTACAO] = {"arquivo": arquivo.name, "questoes": questoes}
            contexto.update(conferir_importacao(questoes), arquivo=arquivo.name)
    return render(request, "painel/importar_gabarito.html", contexto)


@require_POST
def confirmar_importacao(request: HttpRequest) -> HttpResponse:
    pendente = request.session.get(CHAVE_IMPORTACAO)
    if not pendente:
        messages.error(request, "Nenhuma importação pendente. Envie o documento de novo.")
        return redirect("importar_gabarito")
    conferencia = conferir_importacao(pendente["questoes"])
    if conferencia["bloqueada"]:
        messages.error(request, "O documento tem erros. Corrija e envie de novo.")
        return redirect("importar_gabarito")
    sobrescrever = request.POST.get("modo") == "todas"
    campos = ("numero", "titulo", "sentimento_esperado", *CAMPOS_DE_TEXTO, *CAMPOS_DE_LISTA)
    criadas = atualizadas = 0
    with transaction.atomic():
        for questao in conferencia["questoes"]:
            if questao["existe"] and not sobrescrever:
                continue
            _, criada = Questao.objects.update_or_create(
                codigo=questao["codigo"], defaults={campo: questao[campo] for campo in campos}
            )
            criadas += criada
            atualizadas += not criada
    del request.session[CHAVE_IMPORTACAO]
    partes = [f"{criadas} questões cadastradas"]
    if sobrescrever:
        partes.append(f"{atualizadas} sobrescritas")
    elif conferencia["existentes"]:
        partes.append(f"{conferencia['existentes']} já existentes mantidas")
    messages.success(request, f"Importação concluída: {', '.join(partes)}.")
    return redirect("gabarito")


def rodadas(request: HttpRequest) -> HttpResponse:
    total_questoes = Questao.objects.count()
    if request.method == "POST":
        formulario = RodadaForm(request.POST)
        if not total_questoes:
            formulario.add_error(None, "Cadastre ao menos uma questão no gabarito.")
        if formulario.is_valid():
            indice = formulario.cleaned_data["indice"]
            questoes = formulario.cleaned_data["questoes"]
            rodada = Rodada.objects.create(
                indice=indice,
                total=2 * len(questoes),
                config=indice.config_aplicada(carregar_config(settings.RAG_CONFIG)),
            )
            comando = [sys.executable, "manage.py", "executar_rodada", str(rodada.pk), "--questoes"]
            subprocess.Popen(comando + [str(questao.pk) for questao in questoes], cwd=settings.BASE_DIR)
            return redirect("rodada", pk=rodada.pk)
    else:
        ativo = Path(carregar_config(settings.RAG_CONFIG)["caminhos"]["indice"]).name
        formulario = RodadaForm(
            initial={"indice": Indice.objects.filter(nome=ativo).first(), "questoes": Questao.objects.all()}
        )
    todas = Rodada.objects.select_related("indice").annotate(feitas=Count("execucoes")).order_by("-criada_em")
    return render(
        request,
        "painel/rodadas.html",
        {
            "formulario": formulario,
            "rodadas": todas,
            "total_questoes": total_questoes,
            "executando": any(rodada.status == Rodada.Status.EXECUTANDO for rodada in todas),
        },
    )


CRITERIOS = (
    {
        "chave": "fidelidade",
        "nome": "Fidelidade",
        "unidade": "citações com respaldo",
        "olha": "Se cada citação da resposta (processo, ementa, artigo) tem respaldo no gabarito ou no DataJud, ou se foi inventada.",
    },
    {
        "chave": "precisao",
        "nome": "Precisão",
        "unidade": "afirmações corretas",
        "olha": "Se o que a resposta afirma está correto segundo a resposta esperada e as referências: tese, sentimento e fundamentos.",
    },
    {
        "chave": "completude",
        "nome": "Completude",
        "unidade": "elementos",
        "olha": "Se a resposta entrega tudo que a pergunta pediu: pontos obrigatórios, 3 decisões com número e ementa e o sentimento.",
    },
)


def resumir_criterio(blocos: list[dict]) -> dict:
    return {
        "acertos": sum(bloco["fracao"].acertos for bloco in blocos),
        "total": sum(bloco["fracao"].total for bloco in blocos),
        "situacoes": Counter(item.situacao for bloco in blocos for item in bloco["itens"]).items(),
    }


class RodadaView(DetailView):
    model = Rodada

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["julgamentos"] = self.object.julgamentos()
        escolhido = self.request.GET.get("julgamento", "")
        julgamento = int(escolhido) if escolhido.isdigit() else max(contexto["julgamentos"], default=1)
        contexto["julgamento"] = julgamento
        avaliacoes_do_julgamento = Avaliacao.objects.filter(execucao__rodada=self.object, julgamento=julgamento)
        por_execucao = {avaliacao.execucao_id: avaliacao for avaliacao in avaliacoes_do_julgamento}
        linhas = {}
        execucoes = self.object.execucoes.filter(questao__isnull=False).select_related("questao").order_by("questao__numero", "pk")
        for execucao in execucoes:
            linha = linhas.setdefault(execucao.questao_id, {"questao": execucao.questao, "pergunta": execucao.pergunta})
            linha["com_rag" if execucao.indice_id else "sem_rag"] = execucao
        for linha in linhas.values():
            linha["respostas"] = [(rotulo, linha.get(chave)) for chave, rotulo in SISTEMAS]
            avaliacoes = [execucao and por_execucao.get(execucao.pk) for _, execucao in linha["respostas"]]
            linha["avaliacoes"] = avaliacoes
            linha["delta"] = avaliacoes[0].nota - avaliacoes[1].nota if all(avaliacoes) else None
            blocos = [avaliacao and avaliacao.blocos() for avaliacao in avaliacoes]
            linha["criterios"] = [
                {
                    **criterio,
                    "celulas": [
                        {"rotulo": rotulo, "avaliacao": avaliacao, "bloco": bloco and bloco[criterio["chave"]]}
                        for (rotulo, _), avaliacao, bloco in zip(linha["respostas"], avaliacoes, blocos)
                    ],
                }
                for criterio in CRITERIOS
            ]
        contexto["linhas"] = list(linhas.values())
        contexto["avaliada"] = any(any(linha["avaliacoes"]) for linha in contexto["linhas"])
        contexto["criterios"] = []
        for posicao, criterio in enumerate(CRITERIOS):
            celulas = [linha["criterios"][posicao]["celulas"] for linha in contexto["linhas"]]
            contexto["criterios"].append({
                **criterio,
                "linhas": [(linha["questao"], celula) for linha, celula in zip(contexto["linhas"], celulas)],
                "resumo": [
                    {"rotulo": rotulo, **resumir_criterio([celula[sistema]["bloco"] for celula in celulas if celula[sistema]["bloco"]])}
                    for sistema, (_, rotulo) in enumerate(SISTEMAS)
                ],
            })
        contexto["feitas"] = self.object.execucoes.count()
        contexto["modelos_juiz"] = (
            avaliacoes_do_julgamento.order_by("modelo")
            .values_list("modelo", flat=True)
            .distinct()
        )
        contexto["prompts_juiz"] = (
            avaliacoes_do_julgamento.order_by("prompt")
            .values_list("prompt", flat=True)
            .distinct()
        )
        contexto["placar"] = placar(self.object, julgamento)
        com_rag, sem_rag = contexto["placar"]
        if com_rag["nota_media"] is not None and sem_rag["nota_media"] is not None:
            contexto["delta_medio"] = com_rag["nota_media"] - sem_rag["nota_media"]
        contexto["nao_verificados"] = sum(
            list(avaliacao.processos.values()).count("nao_verificado") for avaliacao in avaliacoes_do_julgamento
        )
        contexto["delta_verificado"], contexto["questoes_verificadas"] = delta_verificado(self.object, julgamento)
        contexto["pendencias"] = []
        for linha in contexto["linhas"]:
            numeros = [
                [numero for numero, situacao in avaliacao.processos.items() if situacao == "nao_verificado"]
                if avaliacao
                else []
                for avaliacao in linha["avaliacoes"]
            ]
            if any(numeros):
                contexto["pendencias"].append({"questao": linha["questao"], "numeros": numeros})
        contexto["pode_reavaliar"] = (
            self.object.status == Rodada.Status.CONCLUIDA
            and self.object.status_avaliacao != Rodada.StatusAvaliacao.AVALIANDO
            and julgamento == max(contexto["julgamentos"], default=1)
        )
        return contexto


def exportar_rodadas(request: HttpRequest) -> HttpResponse:
    selecionadas = Rodada.objects.filter(
        pk__in=request.GET.getlist("rodada"), status_avaliacao=Rodada.StatusAvaliacao.CONCLUIDA
    )
    if not selecionadas.exists():
        messages.error(request, "Selecione ao menos uma rodada avaliada para exportar.")
        return redirect("rodadas")
    nome = gerar_nome("rodadas", timezone.localtime(timezone.now()))
    resposta = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{nome}.xlsx"'},
    )
    planilha = BytesIO()
    gravar_planilha(planilha, selecionadas)
    resposta.write(planilha.getvalue())
    return resposta


@require_POST
def avaliar_rodada(request: HttpRequest, pk: int) -> HttpResponse:
    rodada = get_object_or_404(Rodada, pk=pk, status=Rodada.Status.CONCLUIDA)
    if rodada.status_avaliacao != Rodada.StatusAvaliacao.AVALIANDO:
        rodada.status_avaliacao = Rodada.StatusAvaliacao.AVALIANDO
        rodada.erro_avaliacao = ""
        rodada.save()
        comando = [sys.executable, "manage.py", "avaliar_rodada", str(rodada.pk)]
        if request.POST.get("novo"):
            comando.append("--novo")
        questoes = [pk for pk in request.POST.getlist("questao") if pk.isdigit()]
        if questoes:
            comando += ["--questoes", *questoes]
        subprocess.Popen(comando, cwd=settings.BASE_DIR)
    return redirect("rodada", pk=rodada.pk)
