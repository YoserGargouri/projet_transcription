"""
Adaptateur « Chat Completions » compatible OpenAI : un seul code pour Gemini (endpoint
OpenAI-compatible), Groq, OpenRouter, Ollama local, etc. Configuré uniquement par .env :

    LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
    LLM_API_KEY=...
    LLM_MODEL=gemini-flash-latest
    LLM_JSON_MODE=json_schema      # ou json_object si le fournisseur ne gère pas json_schema

En mode json_schema, si le fournisseur refuse response_format (HTTP 400), on bascule une fois
pour toutes en json_object, avec le schéma recopié dans le message système. La validation
finale est toujours faite par pydantic dans la passerelle : on ne fait pas confiance au
fournisseur pour respecter le schéma.
"""
from __future__ import annotations

import json
import time

import requests

from agentkit.llm.providers.base import ProviderResponse

REESSAIS = (1.0, 3.0)   # attentes (s) avant les nouvelles tentatives sur 429 / 5xx (surcharge passagère)


class OpenAICompatibleProvider:
    def __init__(self, base_url: str, api_key: str, model: str, json_mode: str = "json_schema",
                 timeout_s: float = 30.0, reasoning_effort: str = ""):
        if not base_url or not model:
            raise ValueError("LLM_BASE_URL et LLM_MODEL sont nécessaires")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.json_mode = json_mode
        self.timeout_s = timeout_s
        # Modèles « qui réfléchissent » (Gemini 3, GPT-5...) : effort bas = réponse en 1 à 3 s au lieu de 10 à 40 s
        self.reasoning_effort = reasoning_effort
        self.name = f"openai-compatible:{self.base_url}"
        self._session = requests.Session()

    def _corps(self, messages, json_schema):
        corps = {"model": self.model, "messages": messages, "temperature": 0}
        if self.reasoning_effort:
            corps["reasoning_effort"] = self.reasoning_effort
        if self.json_mode == "json_schema":
            corps["response_format"] = {"type": "json_schema",
                                        "json_schema": {"name": "sortie", "schema": json_schema}}
        elif self.json_mode == "json_object":
            consigne = {"role": "system", "content": "Réponds uniquement avec un objet JSON valide conforme à ce "
                                                     "schéma JSON :\n" + json.dumps(json_schema, ensure_ascii=False)}
            corps["messages"] = [consigne, *messages]
            corps["response_format"] = {"type": "json_object"}
        return corps

    def _envoyer(self, url, corps, entetes):
        for attente in (*REESSAIS, None):
            r = self._session.post(url, json=corps, headers=entetes, timeout=self.timeout_s)
            if r.status_code not in (429, 500, 502, 503, 504) or attente is None:
                return r
            time.sleep(attente)
        return r

    def chat(self, messages: list[dict], json_schema: dict) -> ProviderResponse:
        entetes = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        url = f"{self.base_url}/chat/completions"
        r = self._envoyer(url, self._corps(messages, json_schema), entetes)
        if r.status_code == 400 and self.json_mode == "json_schema" and "response_format" in r.text:
            self.json_mode = "json_object"  # le fournisseur ne gère pas json_schema
            r = self._envoyer(url, self._corps(messages, json_schema), entetes)
        r.raise_for_status()
        d = r.json()
        u = d.get("usage") or {}
        return ProviderResponse(text=d["choices"][0]["message"].get("content") or "",
                                prompt_tokens=u.get("prompt_tokens", 0),
                                completion_tokens=u.get("completion_tokens", 0))
