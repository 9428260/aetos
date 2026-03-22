from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://aetos:aetos@localhost:5432/aetos"
    anthropic_api_key: str = ""
    interval_seconds: int = 300  # execution loop interval
    log_level: str = "INFO"

    # LLM / embedding providers
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = ""
    azure_openai_api_version: str = ""
    azure_openai_embedding_deployment: str = ""
    openai_embedding_model: str = ""

    # Weather integration
    openweather_api_key: str = ""
    openweather_city: str = "Seoul"
    openweather_lat: float = 37.5665
    openweather_lon: float = 126.9780
    openweather_units: str = "metric"

    # Reward weights
    w1_cost_saving: float = 0.30
    w2_solar_roi: float = 0.20
    w3_ess_profit: float = 0.30
    w4_degradation: float = 0.10
    w5_risk: float = 0.10

    # ESS parameters
    ess_capacity_kwh: float = 100.0
    ess_max_charge_kw: float = 50.0
    ess_max_discharge_kw: float = 50.0
    ess_degradation_cost_per_kwh: float = 0.002  # $/kWh cycled

    # Optimizer
    optimizer_iterations: int = 20


settings = Settings()
