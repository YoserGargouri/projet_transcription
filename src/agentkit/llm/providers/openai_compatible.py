"""
Adaptateur « Chat Completions » compatible OpenAI : un seul code pour Gemini (endpoint
OpenAI-compatible), Groq, OpenRouter, Ollama local, etc. Configuré uniquement par .env :

    LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
    LLM_API_KEY=...
    LLM_MODEL=gemini-3.5-flash-lite
    LLM_FALLBACK_MODELS=gemini-flash-lite-latest   # modèles de secours, essayés dans l'ordre
    LLM_JSON_MODE=json_schema      # ou json_object si le fournisseur ne gère pas json_schema
    LLM_TIMEOUT_S=10               # budget TOTAL d'un appel, secours compris

Surcharge du fournisseur (429, 5xx, délai dépassé) : on passe tout de suite au modèle suivant
(sans attendre : au téléphone, chaque seconde compte), en boucle tant que le budget le permet.
Budget épuisé : exception, et l'agent continue le tour avec les règles.

En mode json_schema, si le fournisseur refuse response_format (HTTP 400), on bascule une fois
pour toutes en json_object, avec le schéma recopié dans le message système. La validation
finale est toujours faite par pydantic dans la passerelle : on ne fait pas confiance au
fournisseur pour respecter le schéma.
"""
from __future__ import annotations

import json
import logging
import time

import requests

from agentkit.llm.providers.base import ProviderResponse

log = logging.getLogger("agentkit.llm")
SURCHARGE = (429, 500, 502, 503, 504)
DELAI_MIN_S = 1.0          # en dessous, on n'entame pas une nouvelle tentative


class OpenAICompatibleProvider:
    def __init__(self, base_url: str, api_key: str, model: str, json_mode: str = "json_schema",
                 timeout_s: float = 30.0, reasoning_effort: str = "", fallback_models: list[str] | None = None):
        if not base_url or not model:
            raise ValueError("LLM_BASE_URL et LLM_MODEL sont nécessaires")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.fallback_models = [m for m in (fallback_models or []) if m and m != model]
        self.json_mode = json_mode
        self.timeout_s = timeout_s
        # Modèles « qui réfléchissent » (Gemini 3, GPT-5...) : effort bas = réponse en 1 à 3 s au lieu de 10 à 40 s
        self.reasoning_effort = reasoning_effort
        self.name = f"openai-compatible:{self.base_url}"
        self.last_model = model
        self._session = requests.Session()

    def _corps(self, modele, messages, json_schema):
        corps = {"model": modele, "messages": messages, "temperature": 0}
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

    def chat(self, messages: list[dict], json_schema: dict) -> ProviderResponse:
        entetes = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        url = f"{self.base_url}/chat/completions"
        modeles = [self.model, *self.fallback_models]
        fin = time.monotonic() + self.timeout_s
        derniere: Exception | None = None
        i = 0
        while (reste := fin - time.monotonic()) >= DELAI_MIN_S:
            modele = modeles[i % len(modeles)]
            # S'il reste un modèle de secours, on lui garde une part du budget
            delai = reste if len(modeles) == 1 else max(DELAI_MIN_S, min(reste, self.timeout_s * 0.6))
            try:
                r = self._session.post(url, json=self._corps(modele, messages, json_schema), headers=entetes,
                                       timeout=delai)
            except requests.Timeout as e:
                log.warning("%s : pas de réponse en %.1f s, modèle suivant", modele, delai)
                derniere, i = e, i + 1
                continue
            if r.status_code == 400 and self.json_mode == "json_schema" and "response_format" in r.text:
                self.json_mode = "json_object"  # le fournisseur ne gère pas json_schema : on rejoue
                continue
            if r.status_code in SURCHARGE:
                log.warning("%s : HTTP %d (surcharge), modèle suivant", modele, r.status_code)
                derniere, i = requests.HTTPError(f"HTTP {r.status_code} ({modele})", response=r), i + 1
                if len(modeles) == 1:
                    time.sleep(min(1.0, max(0.0, fin - time.monotonic() - DELAI_MIN_S)))
                continue
            r.raise_for_status()
            d = r.json()
            u = d.get("usage") or {}
            self.last_model = modele
            if modele != self.model:
                log.info("réponse fournie par le modèle de secours %s", modele)
            return ProviderResponse(text=d["choices"][0]["message"].get("content") or "",
                                    prompt_tokens=u.get("prompt_tokens", 0),
                                    completion_tokens=u.get("completion_tokens", 0))
        raise derniere or TimeoutError(f"aucune réponse en {self.timeout_s} s")
