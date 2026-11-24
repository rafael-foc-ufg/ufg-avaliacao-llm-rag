import copy

from django import forms
from django.core.validators import FileExtensionValidator

from painel.models import Indice, Questao

FONTES = [("cjf", "Jurisprudência"), ("legislacao", "Legislação")]
ESFORCOS_GROQ = [
    ("", "Padrão do modelo"),
    ("low", "low"),
    ("medium", "medium"),
    ("high", "high"),
    ("none", "none"),
    ("default", "default"),
]


def ajustes_do_config(config: dict) -> dict:
    return {
        "provedor": config["provedor"],
        "modelo_bedrock": config["modelos"]["bedrock"],
        "modelo_groq": config["modelos"]["groq"],
        "raciocinio_groq": config["geracao"]["raciocinio_groq"],
        "temperatura": config["geracao"]["temperatura"],
        "max_tokens": config["geracao"]["max_tokens"],
        "candidatos_jurisprudencia": config["recuperacao"]["candidatos_jurisprudencia"],
        "candidatos_legislacao": config["recuperacao"]["candidatos_legislacao"],
        "top_k": config["recuperacao"]["top_k"],
        "piso_por_fonte": config["recuperacao"]["piso_por_fonte"],
    }


def aplicar_ajustes(config: dict, ajustes: dict) -> dict:
    """Devolve uma copia; chunking, caminhos e embedding ficam como estao."""
    aplicada = copy.deepcopy(config)
    aplicada["provedor"] = ajustes["provedor"]
    aplicada["modelos"]["bedrock"] = ajustes["modelo_bedrock"]
    aplicada["modelos"]["groq"] = ajustes["modelo_groq"]
    aplicada["geracao"]["raciocinio_groq"] = ajustes["raciocinio_groq"]
    aplicada["geracao"]["temperatura"] = ajustes["temperatura"]
    aplicada["geracao"]["max_tokens"] = ajustes["max_tokens"]
    aplicada["recuperacao"]["candidatos_jurisprudencia"] = ajustes["candidatos_jurisprudencia"]
    aplicada["recuperacao"]["candidatos_legislacao"] = ajustes["candidatos_legislacao"]
    aplicada["recuperacao"]["top_k"] = ajustes["top_k"]
    aplicada["recuperacao"]["piso_por_fonte"] = ajustes["piso_por_fonte"]
    return aplicada


class AjustesForm(forms.Form):
    provedor = forms.ChoiceField(
        label="Provedor",
        choices=[("bedrock", "Bedrock"), ("groq", "Groq")],
        help_text="Serviço que gera as respostas e roda o juiz. Só os modelos do provedor escolhido são usados.",
    )
    modelo_bedrock = forms.CharField(
        label="Modelo no Bedrock",
        max_length=100,
        help_text="Identificador do modelo na AWS, usado quando o provedor é Bedrock.",
    )
    modelo_groq = forms.CharField(
        label="Modelo no Groq",
        max_length=100,
        widget=forms.TextInput(attrs={"list": "modelos-groq"}),
        help_text="Nome do modelo no Groq, usado quando o provedor é Groq. Escolha da lista ou digite outro.",
    )
    raciocinio_groq = forms.ChoiceField(
        label="Raciocínio no Groq",
        required=False,
        choices=ESFORCOS_GROQ,
        help_text="Esforço de raciocínio. Conta no máximo de tokens: sem folga, a resposta sai vazia. "
        "gpt-oss aceita low, medium e high; qwen aceita none e default.",
    )
    temperatura = forms.FloatField(
        label="Temperatura",
        min_value=0,
        max_value=1,
        help_text="De 0 a 1. Perto de 0, respostas mais estáveis; perto de 1, mais variadas.",
    )
    max_tokens = forms.IntegerField(
        label="Máximo de tokens",
        min_value=1,
        help_text="Tamanho máximo da resposta gerada. Também limita a resposta do juiz.",
    )
    candidatos_jurisprudencia = forms.IntegerField(
        label="Candidatos de jurisprudência",
        min_value=1,
        help_text="Trechos de acórdãos buscados no índice antes do rerank.",
    )
    candidatos_legislacao = forms.IntegerField(
        label="Candidatos de legislação",
        min_value=1,
        help_text="Trechos de leis buscados no índice antes do rerank.",
    )
    top_k = forms.IntegerField(
        label="Trechos enviados ao modelo",
        min_value=1,
        help_text="Quantos dos candidatos, já reordenados pelo rerank, vão no contexto da pergunta.",
    )
    piso_por_fonte = forms.IntegerField(
        label="Piso por fonte",
        min_value=0,
        help_text="Mínimo de trechos de jurisprudência e de legislação entre os enviados. 0 desliga.",
    )

    def clean(self):
        dados = super().clean()
        top_k = dados.get("top_k")
        jurisprudencia = dados.get("candidatos_jurisprudencia")
        legislacao = dados.get("candidatos_legislacao")
        piso = dados.get("piso_por_fonte")
        if None not in (top_k, jurisprudencia, legislacao) and top_k > jurisprudencia + legislacao:
            self.add_error("top_k", "Os trechos enviados não podem superar a soma dos candidatos.")
        if None not in (top_k, piso) and 2 * piso > top_k:
            self.add_error("piso_por_fonte", "O dobro do piso não pode superar os trechos enviados.")
        return dados


class CredenciaisForm(forms.Form):
    groq_api_key = forms.CharField(
        label="Chave da API do Groq",
        max_length=200,
        widget=forms.PasswordInput,
        help_text="Crie em console.groq.com/keys. Fica gravada no arquivo .env desta máquina.",
    )


class JuizForm(forms.Form):
    modelo = forms.CharField(
        label="Modelo juiz no Bedrock",
        max_length=100,
        help_text="Identificador do modelo na AWS, usado quando o provedor é Bedrock.",
    )
    modelo_groq = forms.CharField(
        label="Modelo juiz no Groq",
        max_length=100,
        widget=forms.TextInput(attrs={"list": "modelos-groq"}),
        help_text="Usado quando o provedor é Groq. Precisa aceitar saída em JSON schema, "
        "como o openai/gpt-oss-120b.",
    )
    raciocinio_groq = forms.ChoiceField(
        label="Raciocínio do juiz no Groq",
        required=False,
        choices=ESFORCOS_GROQ,
        help_text="Raciocínio gasta tokens de saída. No plano gratuito do Groq, o limite de tokens por minuto "
        "vale para entrada e saída somadas; com low, cada avaliação gasta cerca de 4,5 mil tokens.",
    )
    prompt = forms.CharField(
        label="Prompt do juiz",
        widget=forms.Textarea(attrs={"rows": 24}),
        help_text="Instruções de sistema enviadas ao juiz. Os campos do veredito são fixos; "
        "o gabarito e a resposta seguem na mensagem do usuário.",
    )


class NovoIndiceForm(forms.Form):
    prefixo = forms.SlugField(label="Prefixo", max_length=80, help_text="Vira o início do nome da pasta.")
    tamanho = forms.IntegerField(label="Tamanho do chunk", min_value=1)
    overlap = forms.IntegerField(label="Sobreposição", min_value=0)
    embedding = forms.CharField(
        label="Modelo de embedding",
        max_length=100,
        help_text="Id do Bedrock (cohere.embed-multilingual-v3) ou do Hugging Face (BAAI/bge-m3). "
        "Com Hugging Face, embedding e rerank rodam nesta máquina, sem AWS.",
    )
    limite = forms.IntegerField(
        label="Limite de documentos por fonte",
        min_value=1,
        required=False,
        help_text="Vazio usa todos os documentos.",
    )

    def clean(self):
        dados = super().clean()
        tamanho, overlap = dados.get("tamanho"), dados.get("overlap")
        if tamanho is not None and overlap is not None and overlap >= tamanho:
            self.add_error("overlap", "A sobreposição deve ser menor que o tamanho do chunk.")
        return dados


class FiltroChunksForm(forms.Form):
    fonte = forms.ChoiceField(label="Fonte", choices=FONTES, required=False)
    pagina = forms.IntegerField(min_value=1, required=False)
    doc_id = forms.CharField(label="Documento", required=False)


class BuscaForm(forms.Form):
    pergunta = forms.CharField(label="Pergunta", widget=forms.Textarea(attrs={"rows": 3}))
    indice = forms.ModelChoiceField(
        label="Índice", queryset=Indice.objects.filter(status=Indice.Status.PRONTO), empty_label=None
    )


class PerguntaForm(forms.Form):
    pergunta = forms.CharField(label="Pergunta", widget=forms.Textarea(attrs={"rows": 3}))


class ColunaForm(AjustesForm):
    ativa = forms.BooleanField(label="Incluir na comparação", required=False)
    com_rag = forms.BooleanField(label="Usar RAG", required=False)
    indice = forms.ModelChoiceField(
        label="Índice",
        queryset=Indice.objects.filter(status=Indice.Status.PRONTO),
        required=False,
        empty_label="Sem índice",
    )

    def clean(self):
        dados = super().clean()
        if dados.get("com_rag") and not dados.get("indice"):
            self.add_error("indice", "Escolha um índice para usar RAG.")
        return dados


class ListaPorLinhaField(forms.CharField):
    """Edita uma lista de textos como um item por linha; linhas vazias sao descartadas."""

    widget = forms.Textarea(attrs={"rows": 4})

    def prepare_value(self, value):
        return "\n".join(value) if isinstance(value, list) else value

    def to_python(self, value):
        return [linha.strip() for linha in super().to_python(value).splitlines() if linha.strip()]


class QuestaoForm(forms.ModelForm):
    ementas_esperadas = ListaPorLinhaField(label="Ementas esperadas", help_text="Uma ementa por linha.")
    referencias = ListaPorLinhaField(label="Referências", required=False, help_text="Uma referência por linha.")
    pontos_obrigatorios = ListaPorLinhaField(
        label="Pontos obrigatórios", required=False, help_text="Um ponto por linha."
    )
    inaceitavel = ListaPorLinhaField(label="Inaceitável", required=False, help_text="Um erro por linha.")

    class Meta:
        model = Questao
        fields = [
            "codigo",
            "numero",
            "titulo",
            "sentimento_esperado",
            "pergunta",
            "resposta_esperada",
            "ementas_esperadas",
            "referencias",
            "pontos_obrigatorios",
            "inaceitavel",
            "observacao",
        ]
        widgets = {
            "pergunta": forms.Textarea(attrs={"rows": 6}),
            "resposta_esperada": forms.Textarea(attrs={"rows": 4}),
            "observacao": forms.Textarea(attrs={"rows": 2}),
        }


class ImportarGabaritoForm(forms.Form):
    arquivo = forms.FileField(
        label="Documento de mapeamento",
        widget=forms.FileInput(attrs={"accept": ".docx"}),
        validators=[FileExtensionValidator(["docx"], message="Envie um arquivo .docx.")],
        help_text="Arquivo Word (.docx) com as questões no formato \"Questão 01 – Tema\", "
        "seguidas de Pergunta, Resposta esperada, Modelos de Ementas esperadas, Referência, "
        "Pontos obrigatórios, Inaceitável e Observação.",
    )


class RodadaForm(forms.Form):
    indice = forms.ModelChoiceField(
        label="Índice usado no RAG",
        queryset=Indice.objects.filter(status=Indice.Status.PRONTO),
        empty_label=None,
    )
    questoes = forms.ModelMultipleChoiceField(
        label="Questões",
        queryset=Questao.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        error_messages={"required": "Selecione ao menos uma questão."},
    )
