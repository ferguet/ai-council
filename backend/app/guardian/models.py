"""
Modelos del Guardian: lo que la app de mayores manda y lo que recibe.

REGLA QUE MANDA SOBRE TODO LO DEMAS
-----------------------------------
Aqui NUNCA entra nada que la persona haya escrito. Ni su DNI, ni su
telefono, ni su direccion, ni el numero de su tarjeta. Solo entra la
ESTRUCTURA de la pantalla: que etiquetas hay, que botones se ven, que
casillas estan marcadas.

El motivo es simple: quien usa esto es gente a la que ya intentan robar
por todos lados. Si para protegerla mandamos sus datos a un servidor,
somos parte del problema. Ademas los modelos de abajo estan hechos
adrede para que no quepan: no hay ningun sitio donde meter un valor
escrito. Si algun dia alguien lo intenta, no compila.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class CampoVisto(BaseModel):
    """Una casilla de escribir. Se manda QUE le piden, nunca QUE ha puesto."""

    etiqueta: str = Field(max_length=160)   # "Numero de documento", "Correo"
    tipo: str = Field(max_length=20)         # text, email, tel, checkbox...
    marcada: bool | None = None              # solo para casillas de marcar
    vacia: bool = True                       # si tiene algo escrito, SIN decir que


class Pantalla(BaseModel):
    """Lo que se ve en pantalla, sin datos personales."""

    dominio: str = Field(max_length=120)     # "amazon.es". Nunca la direccion
                                             # entera: lleva identificadores
                                             # y a veces datos en la propia url
    titulo: str = Field(default="", max_length=200)
    encabezados: list[str] = Field(default_factory=list, max_length=12)
    botones: list[str] = Field(default_factory=list, max_length=40)
    campos: list[CampoVisto] = Field(default_factory=list, max_length=25)
    textos: list[str] = Field(default_factory=list, max_length=25)
    importes: list[str] = Field(default_factory=list, max_length=10)


class Aviso(BaseModel):
    """Lo que el Guardian contesta. La app lo lee en voz alta."""

    hay_aviso: bool = False
    gravedad: int = 0            # 0 nada, 1 informativo, 4 le van a cobrar ya
    corto: str = ""              # tres o cuatro palabras para la barra
    voz: str = ""                # lo que se dice en alto, en cristiano
    senalar: str | None = None   # texto EXACTO del boton a rodear, si procede
    motivo: str = ""             # para nosotros, no se lee en alto
