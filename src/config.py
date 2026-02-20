"""
Configuration management for Azure AI Document Intelligence Banking Pipeline.
Loads settings from environment variables with validation.
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Azure AI Document Intelligence
    azure_document_intelligence_endpoint: str = Field(
        ..., description="Azure AI Document Intelligence endpoint URL"
    )
    azure_document_intelligence_key: str = Field(
        ..., description="Azure AI Document Intelligence API key"
    )

    # Azure OpenAI
    azure_openai_endpoint: str = Field(..., description="Azure OpenAI endpoint URL")
    azure_openai_api_key: str = Field(..., description="Azure OpenAI API key")
    azure_openai_deployment_name: str = Field(
        default="gpt-4o", description="Azure OpenAI deployment name"
    )
    azure_openai_api_version: str = Field(
        default="2024-12-01-preview", description="Azure OpenAI API version"
    )

    # Database
    database_connection_string: str = Field(
        default="", description="Azure SQL connection string"
    )

    # Application Settings
    confidence_threshold: float = Field(
        default=0.85, description="Minimum confidence score for auto-approval"
    )
    max_file_size_mb: int = Field(
        default=50, description="Maximum upload file size in MB"
    )
    allowed_extensions: str = Field(
        default="pdf,png,jpg,jpeg,tiff,bmp",
        description="Comma-separated allowed file extensions",
    )
    log_level: str = Field(default="INFO", description="Logging level")
    environment: str = Field(default="development", description="Runtime environment")

    @property
    def allowed_extensions_list(self) -> list[str]:
        return [ext.strip().lower() for ext in self.allowed_extensions.split(",")]

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()
