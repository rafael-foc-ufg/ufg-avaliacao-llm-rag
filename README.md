# Painel do RAG — pensão por morte

Painel Django para comparar respostas com e sem RAG e avaliá-las com um modelo juiz.

Este guia é para rodar o painel no **Windows**, sem AWS:

- a geração das respostas e o juiz usam a API gratuita do **Groq**;
- o embedding e o rerank rodam na sua máquina, com modelos do **Hugging Face**.

O `.zip` que você recebeu já traz o código, o banco (`db.sqlite3`) e a base vetorial (`data/index/`). Não é preciso criar o banco nem construir o índice.

---

## 1. Instalar o Python 3.14

1. Baixe o instalador do **Python 3.14** para Windows em <https://www.python.org/downloads/>.
2. Na primeira tela do instalador, marque **"Add python.exe to PATH"**.
3. Abra um PowerShell novo e confira:

   ```powershell
   py -3.14 --version
   ```

## 2. Extrair o projeto

1. Extraia o `.zip` numa pasta sem acentos nem espaços no caminho, por exemplo `C:\projetos\llm-v.0.1`.
2. Abra o PowerShell dentro dessa pasta. Ela deve conter o `manage.py`, o `db.sqlite3` e a pasta `data\index\`.

## 3. Criar a venv e instalar as bibliotecas

```powershell
py -3.14 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Se o PowerShell bloquear o `Activate.ps1`, rode uma vez `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` e tente de novo.

O terminal deve mostrar `(.venv)` no início da linha. Ative a venv (`.venv\Scripts\Activate.ps1`) sempre que abrir um terminal novo para usar o projeto.

## 4. Criar o arquivo `.env`

```powershell
copy .env.exemplo .env
```

Não precisa editar nada. A chave do Groq é informada pelo painel no passo 6, e as variáveis `AWS_*` ficam vazias.

## 5. Rodar o painel

```powershell
python manage.py runserver
```

Abra <http://127.0.0.1:8000>. Para parar, use `Ctrl+C` no terminal.

## 6. Configurar o Groq no painel

1. Crie uma chave gratuita em <https://console.groq.com/keys>.
2. **Padrão do projeto** → seção **Credenciais**: cole a chave e clique em **Salvar chave**. Ela fica gravada no `.env` da sua máquina.
3. Ainda em **Padrão do projeto**: em **Provedor**, escolha **Groq**; em **Modelo no Groq**, escolha um da lista. Clique em **Salvar configurações**.
4. **Índices**: confira se o índice de embedding `BAAI/bge-m3` está ativo. Se não estiver, clique em **Ativar**.
5. **Juiz**: confira o **Modelo juiz no Groq**. O padrão é `openai/gpt-oss-120b`, que aceita a saída estruturada que o juiz exige. Salve.
6. **Padrão do projeto** → **Testar modelos**: todos devem aparecer como "acesso confirmado".

> Na primeira busca ou no primeiro teste, os modelos do Hugging Face são baixados: cerca de 5 GB, sendo 4,3 GB do `BAAI/bge-m3` e 0,5 GB do rerank `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`. Isso acontece uma vez só, e eles ficam no cache do usuário. Depois, cada busca leva uns 3 segundos na CPU. O aviso do Windows sobre *symlinks* pode ser ignorado.

## 7. Usar

- **Busca semântica**: mostra os trechos recuperados, sem LLM.
- **Comparar**: a mesma pergunta em até três colunas, com e sem RAG.
- **Gabarito** → **Rodadas** → **Executar todas as questões**: responde cada questão com e sem RAG. Ao terminar, abra a rodada e clique em **Avaliar com o juiz**.
- **Exportar selecionadas para Excel**, na tela de Rodadas, gera a planilha.

## Limites do Groq gratuito

- O plano gratuito tem limite de tokens por minuto. O juiz faz 3 avaliações por resposta e pode levar 1 a 2 minutos em cada uma. Erro `rate_limit_exceeded` significa que é só esperar e tentar de novo.
- Os modelos atuais do Groq raciocinam antes de responder, e esse raciocínio conta no **Máximo de tokens**. Se a resposta sair vazia, aumente o máximo ou mantenha o **Raciocínio no Groq** em `low` (gpt-oss) ou `none` (qwen).
- Os resultados com Groq servem para teste. Os resultados finais do TCC são gerados com o Claude no Bedrock.

## Problemas comuns

| Sintoma | Causa e solução |
| --- | --- |
| `KeyError: 'DJANGO_SECRET_KEY'` | O `.env` não existe. Refaça o passo 4. |
| `No module named ...` | A venv não está ativa. Veja o `(.venv)` no terminal e refaça a ativação do passo 3. |
| `no such table` | O `db.sqlite3` não está na raiz do projeto. Extraia o `.zip` de novo, sem mover arquivos. |
| "chave do Groq não configurada" | Refaça o passo 6.2. |
| "modelo não encontrado no Groq" | O Groq troca os modelos com frequência. Escolha outro da lista em Padrão do projeto. |
| Índice aparece sem pasta | A pasta do índice não está em `data\index\`. Extraia o `.zip` de novo, sem mover arquivos. |
| `Can't load the model` | O download do modelo foi interrompido. Tente de novo. |
| Erro de credencial AWS | O índice ativo é o da Cohere ou o provedor está em Bedrock. Ative o índice `BAAI/bge-m3` e escolha o provedor Groq. |
