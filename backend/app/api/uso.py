"""
Panel de consumo de tokens/cuota por proveedor de IA.

Antes no habia ninguna forma de ver cuanto se estaba gastando cada
proveedor ni si algun circuito estaba abierto: cuando el Chat Grupal se
quedaba mudo, no habia manera de saber por que sin mirar los logs del
servidor. Este endpoint expone en JSON lo mismo que ya llevan por dentro
el ProviderUsageTracker y el ProviderCircuitBreaker COMPARTIDOS (ver
app.state.provider_usage / app.state.provider_breaker en main.py), para
que Fran pueda verlo desde el navegador sin tocar Render.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["uso"])


@router.get("/uso")
def uso(request: Request) -> dict:
    """Consumo de hoy y estado del circuito, proveedor por proveedor."""
    registry = getattr(request.app.state, "provider_registry", None)
    usage = getattr(request.app.state, "provider_usage", None)
    breaker = getattr(request.app.state, "provider_breaker", None)
    if registry is None or usage is None or breaker is None:
        return {"error": "la app todavia no ha arrancado del todo"}

    proveedores = []
    for info in registry.available():
        name = info["name"]
        count = usage.count_today(name)
        cap = usage.daily_soft_cap
        abierto = breaker.is_open(name)
        proveedores.append({
            "nombre": name,
            "configurado": info["configured"],
            "peticiones_hoy": count,
            "tope_diario": cap,
            "restantes_hoy": usage.remaining_today(name),
            "porcentaje_usado": round(count / cap * 100) if cap else 0,
            "circuito_abierto": abierto,
            "reintenta_en_segundos": round(breaker.seconds_until_retry(name)) if abierto else 0,
        })

    # Los que ya estan al borde o cerrados, primero: son los que a Fran le
    # interesa ver de un vistazo, no los que van sobrados.
    proveedores.sort(key=lambda p: (not p["circuito_abierto"], -p["porcentaje_usado"]))

    return {
        "tope_diario_generico": usage.daily_soft_cap,
        "proveedores": proveedores,
    }
