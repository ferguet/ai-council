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
    sim_autostart: bool = True
    # Si esta configurada (p.ej. Postgres de Supabase), la ciudad se guarda
    # ahi en vez de en el disco local. Necesario para desplegar en un
    # servicio gratuito cuyo disco no es persistente (p.ej. Render free).
    database_url: str | None = None

    # Servidor
    cors_origins: list[str] = ["*"]


@lru_cache
def get_settings() -> Settings:
    """Settings cacheada: se lee el entorno una sola vez por proceso."""
    return Settings()
