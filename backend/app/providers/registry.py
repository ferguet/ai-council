"""
Registro central de proveedores disponibles. El resto del sistema (Director,
Orchestrator, API) pide un proveedor por nombre a traves de esta clase y
nunca importa una implementacion concreta directamente. Anadir un proveedor
nuevo = escribir la clase + una linea aqui.
"""
from __future__ import annotations

from app.core.config import Settings
from app.providers.base import AIProvider
from app.providers.mock_provider import MockProvider
from app.providers.gemini_provider import GeminiProvider
from app.providers.groq_provider import GroqProvider
from app.providers.ollama_provider import OllamaProvider
from app.providers.openai_provider import OpenAIProvider
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.deepseek_provider import DeepSeekProvider
from app.providers.glm_provider import GLMProvider


class ProviderRegistry:
    def __init__(self, settings: Settings) -> None:
        self._providers: dict[str, AIProvider] = {
            "mock": MockProvider(),
            "gemini": GeminiProvider(settings.gemini_api_key),
            "groq": GroqProvider(settings.groq_api_key),
            "ollama": OllamaProvider(settings.ollama_base_url),
            "openai": OpenAIProvider(settings.openai_api_key),
            "anthropic": AnthropicProvider(settings.anthropic_api_key),
            "deepseek": DeepSeekProvider(settings.deepseek_api_key),
            "glm": GLMProvider(settings.glm_api_key),
        }

    def get(self, name: str) -> AIProvider:
        provider = self._providers.get(name)
        if provider is None:
            raise KeyError(
                f"Proveedor '{name}' no existe. Disponibles: {list(self._providers)}"
            )
        return provider

    def available(self) -> list[dict]:
        """Proveedores listos para usarse ahora mismo (con key/local configurado)."""
        return [
            {"name": p.name, "configured": p.is_configured()}
            for p in self._providers.values()
        ]
