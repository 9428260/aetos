from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://aetos:aetos@localhost:5432/aetos"
    anthropic_api_key: str = ""
    interval_seconds: int = 300  # execution loop interval
    log_level: str = "INFO"
    api_read_keys: str = ""
    api_write_keys: str = ""
    api_admin_keys: str = ""
    cors_allow_origins: str = "*"

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
    dispatch_live_enabled: bool = False
    dispatch_require_idempotency_key: bool = True
    dispatch_max_power_kw: float = 100.0
    dispatch_max_market_price: float = 1.0
    a2a_transport: str = "local"
    a2a_remote_endpoint: str = ""
    a2a_remote_timeout_seconds: float = 5.0
    deep_agent_timeout_seconds: float = 20.0
    deep_agent_max_concurrency: int = 4
    deep_agent_requests_per_minute: int = 30
    deep_agent_fallback_mode: str = "workflow"


settings = Settings()
