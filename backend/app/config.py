"""Configuration management using Pydantic Settings."""
import os
from typing import List, Optional
from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import Field
import yaml


class DatabaseConfig(BaseSettings):
    url: str = Field(default="sqlite:///app/data/dvdrip.db")


class FormatConfig(BaseSettings):
    video_codec: str = Field(default="libx265")
    audio_codec: str = Field(default="aac")
    container: str = Field(default="mp4")
    crf: int = Field(default=23, ge=0, le=51)
    preset: str = Field(default="medium")


class LocalDestinationConfig(BaseSettings):
    path: str = Field(default="/archive")


class SSHDestinationConfig(BaseSettings):
    host: str = Field(default="")
    user: str = Field(default="")
    key_path: str = Field(default="")
    remote_path: str = Field(default="")


class DestinationConfig(BaseSettings):
    type: str = Field(default="local")
    local: LocalDestinationConfig = Field(default_factory=LocalDestinationConfig)
    ssh: SSHDestinationConfig = Field(default_factory=SSHDestinationConfig)


class MetadataConfig(BaseSettings):
    providers: List[str] = Field(default_factory=lambda: ["tmdb", "omdb"])
    api_keys: dict = Field(default_factory=dict)


class ServerConfig(BaseSettings):
    port: int = Field(default=80)
    auth_enabled: bool = Field(default=True)
    cors_origins: List[str] = Field(default_factory=lambda: ["*"])


class Settings(BaseSettings):
    """Application settings loaded from environment and config files."""
    
    # Environment
    environment: str = Field(default="production")
    secret_key: str = Field(default="change-me-in-production")
    first_run: bool = Field(default=False)
    
    # Database
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    
    # Transcoding
    formats: FormatConfig = Field(default_factory=FormatConfig)
    
    # Storage
    destination: DestinationConfig = Field(default_factory=DestinationConfig)
    
    # Metadata
    metadata: MetadataConfig = Field(default_factory=MetadataConfig)
    tmdb_api_key: Optional[str] = Field(default=None)
    omdb_api_key: Optional[str] = Field(default=None)
    
    # Server
    server: ServerConfig = Field(default_factory=ServerConfig)
    
    # Redis (for Celery)
    redis_url: str = Field(default="redis://redis:6379/0")
    
    # DVD Device
    dvd_device: str = Field(default="/dev/sr0")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        env_nested_delimiter = "_"


def load_yaml_config(config_path: str = "/app/config/settings.yml") -> dict:
    """Load configuration from YAML file if it exists."""
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            return yaml.safe_load(f) or {}
    return {}


def save_yaml_config(config: dict, config_path: str = "/app/config/settings.yml"):
    """Save configuration to YAML file."""
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    settings = Settings()
    
    # Override with YAML config if exists
    yaml_config = load_yaml_config()
    if yaml_config:
        for key, value in yaml_config.items():
            if hasattr(settings, key):
                # Handle nested config objects properly
                if key == "metadata" and isinstance(value, dict):
                    if "api_keys" in value:
                        settings.metadata.api_keys.update(value["api_keys"])
                    if "providers" in value:
                        settings.metadata.providers = value["providers"]
                elif key == "formats" and isinstance(value, dict):
                    for fmt_key, fmt_val in value.items():
                        if hasattr(settings.formats, fmt_key):
                            setattr(settings.formats, fmt_key, fmt_val)
                elif key == "destination" and isinstance(value, dict):
                    for dest_key, dest_val in value.items():
                        if dest_key == "local" and isinstance(dest_val, dict):
                            for k, v in dest_val.items():
                                if hasattr(settings.destination.local, k):
                                    setattr(settings.destination.local, k, v)
                        elif dest_key == "ssh" and isinstance(dest_val, dict):
                            for k, v in dest_val.items():
                                if hasattr(settings.destination.ssh, k):
                                    setattr(settings.destination.ssh, k, v)
                        elif hasattr(settings.destination, dest_key):
                            setattr(settings.destination, dest_key, dest_val)
                elif key == "database" and isinstance(value, dict):
                    for db_key, db_val in value.items():
                        if hasattr(settings.database, db_key):
                            setattr(settings.database, db_key, db_val)
                elif key == "server" and isinstance(value, dict):
                    for srv_key, srv_val in value.items():
                        if hasattr(settings.server, srv_key):
                            setattr(settings.server, srv_key, srv_val)
                else:
                    setattr(settings, key, value)
    
    # Override API keys from environment if set
    if settings.tmdb_api_key:
        settings.metadata.api_keys["tmdb"] = settings.tmdb_api_key
    if settings.omdb_api_key:
        settings.metadata.api_keys["omdb"] = settings.omdb_api_key
    
    return settings


def update_settings(new_config: dict) -> Settings:
    """Update settings and save to file."""
    config_path = "/app/config/settings.yml"
    current_config = load_yaml_config(config_path)
    current_config.update(new_config)
    save_yaml_config(current_config, config_path)
    
    # Clear cache
    get_settings.cache_clear()
    
    return get_settings()
