GUIA_BEDROCK = "https://docs.aws.amazon.com/pt_br/bedrock/latest/userguide/"

FICHAS = [
    {
        "chave": "bedrock",
        "papel": "Gera as respostas, com e sem RAG.",
        "nome": "Claude Sonnet 4.5",
        "fornecedor": "Anthropic",
        "descricao": "Modelo da Anthropic otimizado para agentes, programação e uso do computador.",
        "guia": GUIA_BEDROCK + "model-card-anthropic-claude-sonnet-4-5.html",
        "ids": {
            "Modelo": "anthropic.claude-sonnet-4-5-20250929-v1:0",
            "Inferência geográfica (EUA)": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
            "Inferência global": "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
        },
        "detalhes": {
            "Lançamento": "30/09/2025",
            "Ciclo de vida": "Legado",
            "Fim de vida (EOL)": "08/04/2027",
            "Janela de contexto": "200 mil tokens",
            "Saída máxima": "64 mil tokens",
            "Raciocínio": "Suportado",
            "Limite de conhecimento": "Abril de 2025",
            "Entrada": "Texto e imagem",
            "Saída": "Texto",
            "APIs no bedrock-runtime": "Converse e Invoke",
            "Cache de prompt": "Mínimo de 1.024 tokens por ponto, até 4 pontos, TTL de 5 min ou 1 h",
            "Níveis de serviço": "Padrão e reservado",
            "Disponibilidade em us-east-1": "Geográfica e global; não há in-region",
        },
    },
    {
        "chave": "juiz",
        "papel": "Avalia as respostas das rodadas, sem saber se usaram RAG.",
        "nome": "Claude Sonnet 5.5",
        "fornecedor": "Anthropic",
        "descricao": "Sonnet mais inteligente e eficiente; avanço sobre o Sonnet 5 em programação e trabalho de conhecimento.",
        "guia": GUIA_BEDROCK + "model-card-anthropic-claude-sonnet-5-5.html",
        "ids": {
            "Modelo": "anthropic.claude-sonnet-5-5",
            "Inferência geográfica (EUA)": "us.anthropic.claude-sonnet-5-5",
            "Inferência global": "global.anthropic.claude-sonnet-5-5",
        },
        "detalhes": {
            "Lançamento": "28/09/2026",
            "Ciclo de vida": "Ativo",
            "Fim de vida (EOL)": "Não antes de 28/09/2027",
            "Janela de contexto": "1 milhão de tokens",
            "Saída máxima": "128 mil tokens",
            "Raciocínio": "Pensamento adaptativo ativo por padrão; esforço baixo, médio, alto ou máximo (padrão alto)",
            "Limite de conhecimento": "Junho de 2026",
            "Entrada": "Texto e imagem",
            "Saída": "Texto",
            "APIs no bedrock-runtime": "Messages, Converse e Invoke",
            "Cache de prompt": "Mínimo de 512 tokens por ponto, até 4 pontos, TTL de 5 min ou 1 h",
            "Níveis de serviço": "Padrão",
            "Disponibilidade em us-east-1": "Geográfica e global; não há in-region",
        },
    },
    {
        "chave": "embedding",
        "papel": "Transforma chunks e perguntas em vetores para a busca no índice.",
        "nome": "Cohere Embed Multilingual v3",
        "fornecedor": "Cohere",
        "descricao": "Embedding de texto com suporte a mais de 100 idiomas, para busca e classificação.",
        "guia": GUIA_BEDROCK + "model-card-cohere-embed-multilingual.html",
        "ids": {
            "Modelo": "cohere.embed-multilingual-v3",
        },
        "detalhes": {
            "Lançamento": "02/11/2023",
            "Ciclo de vida": "Ativo",
            "Janela de contexto": "512 tokens",
            "Entrada": "Texto",
            "Saída": "Embedding",
            "APIs no bedrock-runtime": "Invoke",
            "Níveis de serviço": "Padrão",
            "Disponibilidade em us-east-1": "In-region; sem inferência geográfica ou global",
        },
    },
    {
        "chave": "rerank",
        "papel": "Reordena os candidatos da busca por relevância antes de escolher os trechos enviados.",
        "nome": "Cohere Rerank 3.5",
        "fornecedor": "Cohere",
        "descricao": "Pontua a relevância de documentos para uma consulta, para melhorar a precisão de pipelines de RAG.",
        "guia": GUIA_BEDROCK + "model-card-cohere-rerank-3-5.html",
        "ids": {
            "Modelo": "cohere.rerank-v3-5:0",
        },
        "detalhes": {
            "Lançamento": "02/12/2024",
            "Ciclo de vida": "Ativo",
            "Janela de contexto": "4 mil tokens",
            "Entrada": "Texto",
            "Saída": "Pontuação de relevância",
            "APIs": "Invoke no bedrock-runtime e Rerank no bedrock-agent-runtime",
            "Níveis de serviço": "Padrão",
            "Disponibilidade em us-east-1": "In-region; sem inferência geográfica ou global",
        },
    },
]


def fichas_com_config(config: dict) -> list[dict]:
    """Acrescenta a cada ficha o id do config.yaml e se ele corresponde ao modelo descrito."""
    return [
        {
            **ficha,
            "configurado": config["modelos"][ficha["chave"]],
            "confere": config["modelos"][ficha["chave"]] in ficha["ids"].values(),
        }
        for ficha in FICHAS
    ]
