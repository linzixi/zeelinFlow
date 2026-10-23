from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """扩展的所有环境配置；实例归属 Gateway 生命周期，日志不输出凭据。"""

    model_config = SettingsConfigDict(env_file_encoding="utf-8", extra="ignore")
    database_url: SecretStr
    db_echo: bool = False
    db_auto_create: bool = True
    redis_conn_string: SecretStr
    redis_key_prefix: str = "qingbo"
    cache_enabled: bool = True
    ace_df_tenant: str = "local"
    ace_df_data_workers: int = Field(default=4, ge=1, le=32)
    ace_df_agent_workers: int = Field(default=2, ge=1, le=16)
    ace_df_lease_seconds: int = Field(default=90, ge=10, le=3600)
    ace_df_poll_seconds: float = Field(default=1, ge=0.1, le=60)
    ace_df_agent_timeout_seconds: int = Field(default=1800, ge=30, le=86400)
    ace_df_gateway_url: str = "http://127.0.0.1:8001"
    ace_df_agent_owner_id: str = ""
    ace_df_agent_api_token: SecretStr = SecretStr("")
    ace_df_source_url: str = ""
    ace_df_source_token: SecretStr = SecretStr("")
    gsdata_es_token: SecretStr = Field(default=SecretStr(""), alias="GSDATAS_ES_TOKEN")
    gsdata_es_gateway_url: str = Field(
        default="http://gateway.gsdatas.cn/mg/search/es", alias="GSDATAS_ES_GATEWAY_URL"
    )
    ace_df_output_root: Path = Path(".ace-data")
    sqty_app_id: str = ""
    sqty_app_secret: SecretStr = SecretStr("")
    sqty_api_url: str = "https://aipincustom.gsdata.cn/customapi/shangQi/index/query"
    sgm_sis_enabled: bool = False
    sgm_sis_db_host: str = ""
    sgm_sis_db_port: int = 3306
    sgm_sis_db_name: str = "download_news"
    sgm_sis_db_user: str = ""
    sgm_sis_db_password: SecretStr = SecretStr("")
    sgm_sis_project_id: str = "ADMIN-2021-0004"
    sgm_sis_poll_seconds: int = Field(default=15, ge=5, le=300)
    sgm_sis_timeout_minutes: int = Field(default=60, ge=1, le=120)
    sgm_asr_url: str = ""
    sgm_asr_access_key: SecretStr = SecretStr("")
    sgm_asr_secret_key: SecretStr = SecretStr("")
    sgm_etl_host: str = "http://etl.gsdatas.cn:19615"
    sgm_etl_token: SecretStr = SecretStr("")
    sgm_etl_secret: SecretStr = SecretStr("")
    sgm_etl_timeout: int = Field(default=10, ge=1, le=60)
    sgm_etl_retries: int = Field(default=3, ge=1, le=5)

    @property
    def queue_prefix(self) -> str:
        return f"{self.redis_key_prefix}:ace_df:v1:{self.ace_df_tenant}"
