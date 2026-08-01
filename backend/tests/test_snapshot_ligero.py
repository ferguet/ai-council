"""
La foto que se manda al navegador tiene que ir recortada.

El 26/07 Render suspendio el servicio por agotar los 5 GB de ancho de
banda del mes. La causa: engine.snapshot() mandaba el mundo ENTERO en
cada conexion de WebSocket (personalidades completas de cada IA, y todos
los eventos desde el primer dia, que nunca se borran), y city.html
reintentaba conectarse cada 3 segundos sin freno.

Estos tests fijan las dos mitades del arreglo del lado del servidor:
que se recorta lo que viaja, y -sobre todo- que NO se recorta lo que se
guarda en disco. Confundir esas dos cosas seria mucho peor que el
problema original: perderiamos la memoria de la ciudad para siempre.
"""
from __future__ import annotations

from app.domain.city_enums import EventType
from app.domain.city_models import CityEvent
from app.simulation.engine import SimulationEngine
from app.simulation.persistence import world_to_dict
from app.simulation.world_data import build_default_world


def _mundo_vivido(n_eventos: int = 1000):
    world = build_default_world()
    for i in range(n_eventos):
        world.events.append(
            CityEvent.create(
                EventType.PENSAMIENTO, i // 24, i % 24,
                f"Pensamiento numero {i}", ["gemini"],
            )
        )
    for c in world.citizens.values():
        c.memory = [f"recuerdo {j}" for j in range(50)]
    return world


def _engine(world) -> SimulationEngine:
    """Solo hace falta el atributo .world para snapshot(); construir el
    motor entero exigiria registry, event_bus y store de verdad."""
    engine = SimulationEngine.__new__(SimulationEngine)
    engine.world = world
    return engine


def test_la_foto_no_lleva_la_personalidad_de_las_ias():
    """system_prompt era la mitad del peso y el frontend no lo usa."""
    world = _mundo_vivido()
    foto = _engine(world).snapshot()
    assert foto["citizens"], "el mundo de prueba deberia tener ciudadanos"
    for ciudadano in foto["citizens"].values():
        assert "system_prompt" not in ciudadano


def test_la_foto_recorta_eventos_memoria_y_mensajes():
    world = _mundo_vivido(n_eventos=1000)
    foto = _engine(world).snapshot()

    assert len(foto["events"]) == SimulationEngine._SNAPSHOT_MAX_EVENTS
    # y son los MAS RECIENTES, no los primeros: la ciudad se lee de ahora
    # hacia atras, mandar los 300 primeros de hace semanas seria inutil.
    assert foto["events"][-1]["description"] == "Pensamiento numero 999"

    assert foto["direct_messages"] == []
    for ciudadano in foto["citizens"].values():
        assert len(ciudadano["memory"]) <= SimulationEngine._SNAPSHOT_MAX_MEMORY


def test_lo_que_se_guarda_en_disco_sigue_completo():
    """EL TEST QUE DE VERDAD IMPORTA.

    world_to_dict() es lo que se persiste. Si alguien 'optimiza' tambien
    esto, la ciudad perderia su memoria en el siguiente guardado y no
    habria vuelta atras. snapshot() puede recortar; el guardado no.
    """
    world = _mundo_vivido(n_eventos=1000)
    disco = world_to_dict(world)

    assert len(disco["events"]) == 1000
    for ciudadano in disco["citizens"].values():
        assert ciudadano["system_prompt"], "la personalidad debe guardarse entera"
        assert len(ciudadano["memory"]) == 50


def test_recortar_la_foto_no_toca_el_mundo_en_memoria():
    """snapshot() no puede tener efectos secundarios: si al recortar
    modificase el mundo de verdad, el siguiente guardado escribiria el
    mundo ya mutilado."""
    world = _mundo_vivido(n_eventos=1000)
    _engine(world).snapshot()

    assert len(world.events) == 1000
    for c in world.citizens.values():
        assert len(c.memory) == 50
        assert c.system_prompt
