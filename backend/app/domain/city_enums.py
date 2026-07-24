"""Enumeraciones del dominio de la Ciudad Virtual. Sin dependencias externas,
igual que enums.py del debate, a proposito."""
from enum import Enum


class BuildingType(str, Enum):
    BIBLIOTECA = "biblioteca"
    LABORATORIO = "laboratorio"
    CENTRO_PROGRAMACION = "centro_programacion"
    SALA_DEBATES = "sala_debates"
    PARLAMENTO = "parlamento"
    PLAZA = "plaza"
    VIVIENDAS = "viviendas"
    AYUNTAMIENTO = "ayuntamiento"


class ActivityType(str, Enum):
    INVESTIGAR = "investigar"
    PROGRAMAR = "programar"
    DEBATIR = "debatir"
    VOTAR = "votar"
    GESTIONAR = "gestionar"
    SOCIALIZAR = "socializar"
    DESCANSAR = "descansar"


class EventType(str, Enum):
    LLEGADA = "llegada"
    PENSAMIENTO = "pensamiento"
    PROYECTO_INICIADO = "proyecto_iniciado"
    PROYECTO_AVANCE = "proyecto_avance"
    PROYECTO_COMPLETADO = "proyecto_completado"
    REUNION = "reunion"
    CONVERSACION = "conversacion"
    RELACION = "relacion"
    SUGERENCIA = "sugerencia"
    DUDA = "duda"
    RESPUESTA_PROFESORA = "respuesta_profesora"
    SISTEMA = "sistema"


class ProjectStatus(str, Enum):
    ACTIVO = "activo"
    COMPLETADO = "completado"
    PAUSADO = "pausado"
