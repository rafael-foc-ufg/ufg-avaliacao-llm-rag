import os
from pathlib import Path

import yaml
from dotenv import load_dotenv, set_key


def carregar_config(caminho: Path | str = "config.yaml") -> dict:
    load_dotenv()
    with open(caminho, encoding="utf-8") as arquivo:
        return yaml.safe_load(arquivo)


def salvar_config(config: dict, caminho: Path | str) -> None:
    with open(caminho, "w", encoding="utf-8") as arquivo:
        yaml.safe_dump(config, arquivo, sort_keys=False, allow_unicode=True)


def salvar_credencial(nome: str, valor: str, caminho_env: Path | str) -> None:
    """Grava no .env e no ambiente do processo, para valer sem reiniciar o servidor."""
    set_key(caminho_env, nome, valor)
    os.environ[nome] = valor
