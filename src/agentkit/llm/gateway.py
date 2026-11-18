"""
Passerelle LLM : le seul chemin par lequel le moteur appelle un LLM, quel que soit le fournisseur.

    gateway = gateway_from_env()                 # None si aucun LLM n'est configuré (.env)
    gateway.begin_turn("t3")                     # une conversation = des tours
    sortie = gateway.complete_json(messages, MonModele)   # instance pydantic validée

Garanties :
- sortie JSON validée par pydantic ; si elle est invalide, UNE nouvelle tentative avec le
  message d'erreur, puis InvalidOutput (l'appelant décide : clarifier ou transférer) ;
- cache disque des sorties valides (même requête = 0 coût) ;
- compteurs : appels, requêtes, tentatives, jetons, latence (gateway.usage) ;
- plafond de budget facultatif (LLM_MAX_CALLS, LLM_MAX_TOKENS) ;
- au plus N appels LOGIQUES par tour (N = 1 pour SingleCallPolicy) : un 2e appel dans le
  même tour lève TurnCallLimit. La nouvelle tentative sur sortie invalide fait partie du
  même appel logique (elle est comptée à part dans usage.retries).
"""
from __future__ import annotations

import json
import re
import time
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from agentkit import config
from agentkit.llm.cache import ResponseCache, cle_requete
from agentkit.llm.usage import Usage

M = TypeVar("M", bound=BaseModel)


class LLMError(Exception):
    """Échec du LLM (réseau, HTTP...) : l'appelant se replie sur les règles."""


class BudgetExceeded(LLMError):
    pass


class TurnCallLimit(LLMError):
    """Trop d'appels LLM dans un même tour (règle « un appel par tour »)."""


class InvalidOutput(LLMError):
    def __init__(self, message: str, raw: dict | None):
        super().__init__(message)
        self.raw = raw  # dernier JSON reçu (s'il était lisible), pour un éventuel sauvetage


def _extraire_json(texte: str) -> str:
    """Accepte un JSON entouré de ```json ... ``` (certains fournisseurs l'ajoutent)."""
    m = re.search(r"```(?:json)?\s*(.*?)```", texte, re.DOTALL)
    return (m.group(1) if m else texte).strip()


def _erreurs_courtes(e: Exception) -> str:
    if isinstance(e, ValidationError):
        return "; ".join(f"{'.'.join(map(str, x['loc']))} : {x['msg']}" for x in e.errors()[:5])
    return str(e)[:300]


class LLMGateway:
    def __init__(self, provider, cache: ResponseCache | None = None, max_calls: int = 0, max_tokens: int = 0):
        self.provider = provider
        self.cache = cache
        self.max_calls = max_calls
        self.max_tokens = max_tokens
        self.usage = Usage()
        self._tour: str | None = None
        self._appels_tour = 0
        self._max_par_tour = 1

    @property
    def name(self) -> str:
        return f"{self.provider.name}/{self.provider.model}"

    def begin_turn(self, turn_id: str, max_calls: int = 1) -> None:
        self._tour, self._appels_tour, self._max_par_tour = turn_id, 0, max_calls

    def calls_this_turn(self) -> int:
        return self._appels_tour

    def complete_json(self, messages: list[dict], output_model: type[M], retries: int = 1) -> M:
        if self._tour is not None and self._appels_tour >= self._max_par_tour:
            raise TurnCallLimit(f"tour {self._tour} : déjà {self._appels_tour} appel(s) LLM")
        if self.max_calls and self.usage.logical_calls >= self.max_calls:
            raise BudgetExceeded(f"plafond de {self.max_calls} appels atteint")
        if self.max_tokens and self.usage.total_tokens >= self.max_tokens:
            raise BudgetExceeded(f"plafond de {self.max_tokens} jetons atteint")
        self.usage.logical_calls += 1
        self._appels_tour += 1
        if self._tour is not None:
            self.usage.per_turn[self._tour] = self.usage.per_turn.get(self._tour, 0) + 1

        schema = output_model.model_json_schema()
        cle = cle_requete(self.provider.name, self.provider.model, messages, schema)
        if self.cache and (en_cache := self.cache.get(cle)) is not None:
            try:
                sortie = output_model.model_validate(en_cache)
                self.usage.cache_hits += 1
                return sortie
            except ValidationError:
                pass  # le schéma a changé depuis : on redemande

        msgs, dernier = list(messages), None
        for tentative in range(retries + 1):
            if tentative:
                self.usage.retries += 1
            t0 = time.perf_counter()
            try:
                rep = self.provider.chat(msgs, schema)
            except Exception as e:  # réseau, HTTP, quota...
                self.usage.errors += 1
                raise LLMError(f"{type(e).__name__} : {str(e)[:200]}") from e
            finally:
                self.usage.latency_s += time.perf_counter() - t0
            self.usage.requests += 1
            self.usage.prompt_tokens += rep.prompt_tokens
            self.usage.completion_tokens += rep.completion_tokens
            try:
                dernier = None
                dernier = json.loads(_extraire_json(rep.text))
                sortie = output_model.model_validate(dernier)
            except (json.JSONDecodeError, ValidationError) as e:
                msgs = msgs + [{"role": "assistant", "content": rep.text},
                               {"role": "user", "content": f"Ta réponse n'est pas valide ({_erreurs_courtes(e)}). "
                                                           "Renvoie uniquement l'objet JSON corrigé."}]
                continue
            if self.cache:
                self.cache.set(cle, sortie.model_dump(mode="json"))
            return sortie
        self.usage.invalid_outputs += 1
        raise InvalidOutput("sortie du LLM invalide après nouvelle tentative",
                            dernier if isinstance(dernier, dict) else None)


def gateway_from_env(use_cache: bool = True) -> LLMGateway | None:
    """Passerelle configurée par .env (LLM_BASE_URL, LLM_API_KEY, LLM_MODEL...), ou None :
    sans LLM, le moteur fonctionne avec les règles seules (NoLLMPolicy)."""
    base_url, modele = config.env("LLM_BASE_URL"), config.env("LLM_MODEL")
    if not base_url or not modele:
        return None
    from agentkit.llm.providers.openai_compatible import OpenAICompatibleProvider

    fournisseur = OpenAICompatibleProvider(base_url, config.env("LLM_API_KEY"), modele,
                                           json_mode=config.env("LLM_JSON_MODE", "json_schema"))
    cache = ResponseCache(config.runtime_dir("cache") / "llm.sqlite") if use_cache else None
    return LLMGateway(fournisseur, cache, max_calls=config.env_int("LLM_MAX_CALLS"),
                      max_tokens=config.env_int("LLM_MAX_TOKENS"))
