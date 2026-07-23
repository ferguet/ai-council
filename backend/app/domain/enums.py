"""Enumeraciones del dominio. Sin dependencias externas a proposito.

Se usa "class X(str, Enum)" en vez de StrEnum (solo disponible desde
Python 3.11) para mantener compatibilidad con 3.10, mas extendido en
entornos de despliegue actuales.
"""
from enum import Enum


class MessageType(str, Enum):
    STATEMENT = "statement"          # una IA da su opinion/analisis
    QUESTION = "question"            # una IA pregunta a otra
    EVIDENCE_REQUEST = "evidence_request"  # una IA pide pruebas/fuentes
    CLARIFICATION = "clarification"  # se pide aclarar algo
    SUMMARY = "summary"              # el Director resume el debate
    CONSENSUS = "consensus"          # se declara consenso alcanzado
    USER = "user"                    # mensaje del usuario humano
    SYSTEM = "system"                # mensajes de sistema (inicio/fin, avisos)


class DebateStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    SUMMARIZING = "summarizing"
    CONSENSUS_REACHED = "consensus_reached"
    ENDED = "ended"
    DEADLOCKED = "deadlocked"  # el Director detecta que no se avanza


class DirectorAction(str, Enum):
    CONTINUE = "continue"
    SUMMARIZE = "summarize"
    END = "end"
    REQUEST_EVIDENCE = "request_evidence"
    ASK_CLARIFICATION = "ask_clarification"
    CONSENSUS = "consensus"
    DEADLOCK = "deadlock"
