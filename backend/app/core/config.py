"""
Configuracion central de la aplicacion, cargada desde variables de entorno.

Se usa pydantic-settings para que la config sea tipada y validada en el
arranque, en vez de leer os.environ sueltos por todo el codigo.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Proveedores
    gemini_api_key: str | None = None
    groq_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    deepseek_api_key: str | None = None
    glm_api_key: str | None = None
    mistral_api_key: str | None = None
    cerebras_api_key: str | None = None
    openrouter_api_key: str | None = None
    nvidia_api_key: str | None = None
    # Segunda clave de Gemini, separada de la de la ciudadana "Gemini": la
    # usan la Profesora y el Moderador, para no compartir cuota/limite con
    # el laboratorio.
    gemini_api_key_2: str | None = None

    # Director
    director_provider: str = "mock"
    director_model: str = "director-v1"

    # Limites de seguridad
    max_debate_turns: int = 20

    # Ciudad Virtual (Persistent AI Civilization)
    sim_tick_seconds: int = 60          # cuanto tiempo real dura 1 tick del motor
    sim_hours_per_tick: int = 1          # cuantas horas simuladas avanza cada tick
    sim_real_ai_interval_minutes: int = 15  # minimo tiempo real entre llamadas reales de "pensamiento" por ciudadano
    # Si nadie abre la Ciudad en estos minutos, los ciudadanos dejan de pensar
    # con IA real (el reloj y sus rutinas siguen: eso no cuesta nada). Era la
    # mayor fuga de cuota del proyecto: ~11 ciudadanos pensando cada 15 min las
    # 24 horas, mirase alguien o no. Con 0 se desactiva y piensan siempre.
    sim_idle_pause_minutes: int = 30
    sim_data_path: str = "data/city_state.json"

    # Periodico diario: resumen periodistico de la ciudad, escrito por una
    # IA sobre eventos reales (no inventados). Usa GLM por defecto porque ya
    # esta configurada para otro ciudadano y no comparte cuota con Gemini
    # (que es el proveedor mas ajustado de limite gratuito en este proyecto).
    news_provider: str = "glm"
    news_model: str = "glm-4.7-flash"
    news_interval_hours: int = 24
    # Si el proveedor principal falla por cuota agotada, se prueba una vez
    # con este proveedor de reserva antes de rendirse y perder la edicion
    # del dia. Cerebras por defecto: nivel gratuito muy generoso (1M
    # tokens/dia) y ningun ciudadano lo usa como personaje, asi que no
    # compite por cuota con nada mas de la app.
    news_fallback_provider: str = "cerebras"
    news_fallback_model: str = "gpt-oss-120b"

    # Chat Grupal (Interfaz de conversacion)
    conversation_data_path: str = "data/conversations.json"
    sim_autostart: bool = True
    # Si esta configurada (p.ej. Postgres de Supabase), la ciudad se guarda
    # ahi en vez de en el disco local. Necesario para desplegar en un
    # servicio gratuito cuyo disco no es persistente (p.ej. Render free).
    database_url: str | None = None

    # Servidor
    cors_origins: list[str] = ["*"]

    # Puerta de entrada: una clave compartida que Fran reparte a mano a
    # quien quiere que use la app, para que no se la pase el enlace a
    # cualquiera. Sin configurar, la puerta queda abierta (desarrollo local).
    access_code: str | None = None

    # Boton "Llamar a Claude" del Chat Grupal: clave SEGUNDA y distinta de
    # ACCESS_CODE, que solo conoce Fran. ACCESS_CODE se reparte a quien
    # invita a charlar con las IA; esta no se reparte a nadie, es solo para
    # que Fran pueda dejar marcada en el chat una peticion de intervencion
    # sin que cualquier visitante invitado pueda tocarla tambien. Sin
    # configurar, el boton queda desactivado (falla cerrado, no abierto).
    claude_call_code: str | None = None

    # Racionamiento diario del Chat Grupal: tope conservador de peticiones
    # reales por proveedor y por dia (UTC), igual para todos porque el
    # limite real de cada uno varia y no siempre es publico. Al llegar al
    # tope, ese proveedor deja de llamarse de verdad el resto del dia y se
    # usa su proveedor de respaldo (ver ProviderUsageTracker y
    # _FALLBACK_PROVIDER en conversation/engine.py). Ajustable sin tocar
    # codigo si se ve que se queda corto o largo en la practica.
    provider_daily_soft_cap: int = 150

    # Busqueda web real para las IA del Chat Grupal (ver
    # app/tools/web_search.py y _SEARCH_ENABLED_CITIZENS en
    # conversation/engine.py). Sin esto configurado, ninguna IA puede
    # buscar de verdad -sigue funcionando la app entera igual, solo que sin
    # esta capacidad extra. Clave gratis en https://tavily.com.
    tavily_api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    """Settings cacheada: se lee el entorno una sola vez por proceso."""
    return Settings()
