"""Valida a exportação do fluxo n8n do DataForge."""

from __future__ import annotations

import json
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
ARQUIVO = RAIZ / "orchestration" / "n8n" / "dataforge_resumo.json"
PREFIXOS_PROIBIDOS = ("ghp_", "ghs_", "github_pat_", "sk-", "xoxb-", "xoxp-")


def _fluxo() -> dict:
    dados = json.loads(ARQUIVO.read_text(encoding="utf-8"))
    assert isinstance(dados, list) and len(dados) == 1
    fluxo = dados[0]
    assert isinstance(fluxo, dict)
    return fluxo


def test_exportacao_n8n_bem_formada():
    fluxo = _fluxo()
    assert fluxo["active"] is False
    assert isinstance(fluxo["name"], str) and fluxo["name"]
    assert isinstance(fluxo["connections"], dict)
    assert isinstance(fluxo["settings"], dict)

    nos = fluxo["nodes"]
    assert isinstance(nos, list) and nos
    nomes: list[str] = []
    tipos: set[str] = set()
    for no in nos:
        for campo in ("id", "name", "type", "typeVersion", "position", "parameters"):
            assert campo in no, campo
        assert isinstance(no["id"], str) and no["id"]
        assert isinstance(no["name"], str) and no["name"]
        assert no["type"].startswith("n8n-nodes-base.")
        assert isinstance(no["typeVersion"], int | float)
        assert isinstance(no["position"], list) and len(no["position"]) == 2
        assert isinstance(no["parameters"], dict)
        nomes.append(no["name"])
        tipos.add(no["type"])

    assert len(nomes) == len(set(nomes))
    assert "n8n-nodes-base.scheduleTrigger" in tipos
    assert "n8n-nodes-base.executeCommand" in tipos
    assert "n8n-nodes-base.httpRequest" in tipos

    comando = next(no for no in nos if no["type"] == "n8n-nodes-base.executeCommand")
    texto = comando["parameters"]["command"]
    assert "python -m dataforge ingest --source all" in texto
    assert "python -m dataforge quality" in texto

    agenda = next(no for no in nos if no["type"] == "n8n-nodes-base.scheduleTrigger")
    intervalo = agenda["parameters"]["rule"]["interval"][0]
    assert intervalo["field"] == "cronExpression"
    assert intervalo["expression"] == "0 6 * * *"

    webhook = next(no for no in nos if no["type"] == "n8n-nodes-base.httpRequest")
    assert webhook["parameters"]["method"] == "POST"
    assert webhook["parameters"]["url"] == "https://webhook.example.com/dataforge/resumo"
    credencial = webhook["credentials"]["httpHeaderAuth"]
    assert "placeholder" in credencial["id"].lower()
    assert "placeholder" in credencial["name"].lower()

    for origem, saidas in fluxo["connections"].items():
        assert origem in nomes
        for grupo in saidas["main"]:
            assert isinstance(grupo, list)
            for elo in grupo:
                assert elo["node"] in nomes
                assert elo["type"] == "main"
                assert isinstance(elo["index"], int)

    bruto = ARQUIVO.read_text(encoding="utf-8")
    for prefixo in PREFIXOS_PROIBIDOS:
        assert prefixo not in bruto
    proibido = re.search(
        r'"(password|secret|api_key|apiKey|token)"\s*:',
        bruto,
        re.IGNORECASE,
    )
    assert proibido is None
