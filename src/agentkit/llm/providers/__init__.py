"""Fournisseurs de LLM : adaptateur compatible OpenAI et FakeLLM pour les tests."""
from agentkit.llm.providers.base import Provider, ProviderResponse
from agentkit.llm.providers.fake import FakeLLM
from agentkit.llm.providers.openai_compatible import OpenAICompatibleProvider

__all__ = ["FakeLLM", "OpenAICompatibleProvider", "Provider", "ProviderResponse"]
