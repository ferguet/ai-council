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
    sim_data_path: str = "data/city_state.json"

    # Periodico diario: resumen periodistico de la ciudad, escrito por una
    # IA sobre eventos reales (no inventados). Usa GLM por defecto porque ya
    # esta configurada para otro ciudadano y no comparte cuota con Gemini
    # (que es el proveedor mas ajustado de limite gratuito en este proyecto).
    news_provider: str = "glm"
    news_model: str = "glm-4.7-flash"
    news_interval_hours: int = 24

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


@lru_cache
def get_settings() -> Settings:
    """Settings cacheada: se lee el entorno una sola vez por proceso."""
    return Settings()
