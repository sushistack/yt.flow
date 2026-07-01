from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="YTFLOW_",
        env_file=".env",
        extra="ignore",
    )

    langfuse_host: str
    langfuse_public_key: str
    langfuse_secret_key: str

    # Single SQLite file shared by LangGraph checkpoints and future SQLModel tables. [AD-7]
    db_path: str = "yt_flow.db"
