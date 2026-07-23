"""
Interfaz comun que deben cumplir todos los proveedores de IA.

Esta es la pieza clave de la arquitectura: el Orchestrator y el Director
solo conocen esta interfaz, nunca un proveedor concreto. Anadir OpenAI,
un modelo nuevo de Mistral, o cualquier otro proveedor futuro es escribir
una clase que implemente esto, sin tocar nada mas del sistema (patron
adaptador / puerto-adaptador de Clean Architecture).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


class ProviderError(RuntimeError):
    """Error al llamar a un proveedor (key invalida, rate limit, red, etc.)."""


class AIProvider(ABC):
    """Puerto que todo proveedor de modelos debe implementar."""

    name: str

    @abstractmethod
    async def stream_chat(
        self, messages: list[ChatMessage], model: str, temperature: float = 0.7
    ) -> AsyncIterator[str]:
        """Genera la respuesta trozo a trozo (para streaming en vivo al frontend)."""
        raise NotImplementedError
        yield ""  # pragma: no cover - hace de esta funcion un generador para mypy

    @abstractmethod
    async def chat(
        self, messages: list[ChatMessage], model: str, temperature: float = 0.7
    ) -> str:
        """Devuelve la respuesta completa de una vez (la usa el Director para decidir)."""
        raise NotImplementedError

    def is_configured(self) -> bool:
        """Si el proveedor tiene lo necesario (p.ej. API key) para funcionar."""
        return True
