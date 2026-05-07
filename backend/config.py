"""
Application configuration with feature flags for optional integrations.

This module centralizes all configuration, making it easy to:
- Run with just sample data (default, zero friction)
- Connect real data sources (Sentry, Azure, etc.)
- Enable real integrations (Linear, Slack)
"""
import os
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from functools import lru_cache


@dataclass
class IntegrationConfig:
    """Configuration for an optional integration."""
    enabled: bool = False
    api_key: Optional[str] = None
    
    @property
    def is_configured(self) -> bool:
        """Check if integration is both enabled AND has credentials."""
        return self.enabled and bool(self.api_key)


@dataclass
class LinearConfig(IntegrationConfig):
    """Linear-specific configuration."""
    team_id: Optional[str] = None
    
    @property
    def is_configured(self) -> bool:
        return self.enabled and bool(self.api_key) and bool(self.team_id)


@dataclass 
class SlackConfig(IntegrationConfig):
    """Slack-specific configuration."""
    channel_id: Optional[str] = None
    signing_secret: Optional[str] = None
    
    @property
    def is_configured(self) -> bool:
        return self.enabled and bool(self.api_key) and bool(self.channel_id)


@dataclass
class AirweaveConfig:
    """Airweave configuration (required for context search)."""
    api_key: Optional[str] = None
    api_url: str = "https://api.airweave.ai"
    collection_id: Optional[str] = None
    
    @property
    def is_configured(self) -> bool:
        return bool(self.api_key) and bool(self.collection_id)


@dataclass
class DataSourceConfig:
    """Data source configuration."""
    # Which source to use: "sample", "azure", "sentry", "datadog"
    source_type: str = "sample"
    
    # Azure Log Analytics
    azure_workspace_id: Optional[str] = None
    azure_client_id: Optional[str] = None
    azure_client_secret: Optional[str] = None
    azure_tenant_id: Optional[str] = None
    
    # Sentry
    sentry_auth_token: Optional[str] = None
    sentry_org_slug: Optional[str] = None
    sentry_project_slug: Optional[str] = None
    sentry_url: str = "https://sentry.io"
    
    # Datadog
    datadog_api_key: Optional[str] = None
    datadog_app_key: Optional[str] = None
    datadog_site: str = "datadoghq.com"
    
    @property
    def azure_configured(self) -> bool:
        return all([
            self.azure_workspace_id,
            self.azure_client_id,
            self.azure_client_secret,
            self.azure_tenant_id,
        ])
    
    @property
    def sentry_configured(self) -> bool:
        return all([
            self.sentry_auth_token,
            self.sentry_org_slug,
        ])
    
    @property
    def datadog_configured(self) -> bool:
        return all([
            self.datadog_api_key,
            self.datadog_app_key,
        ])


@dataclass
class LLMConfig:
    """LLM provider configuration."""
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    
    # Model preferences
    anthropic_model: str = "claude-sonnet-4-20250514"
    openai_model: str = "gpt-4o"
    
    @property
    def provider(self) -> Optional[str]:
        """Get the active LLM provider."""
        if self.anthropic_api_key:
            return "anthropic"
        elif self.openai_api_key:
            return "openai"
        return None
    
    @property
    def is_configured(self) -> bool:
        return self.provider is not None
    
    @property
    def model(self) -> Optional[str]:
        """Get the model name for the active provider."""
        if self.provider == "anthropic":
            return self.anthropic_model
        elif self.provider == "openai":
            return self.openai_model
        return None


@dataclass
class Config:
    """
    Main application configuration.
    
    Collects all configuration from environment variables.
    Integrations are disabled by default for zero-friction demo experience.
    """
    # Required
    airweave: AirweaveConfig = field(default_factory=AirweaveConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    
    # Data source (sample by default)
    data_source: DataSourceConfig = field(default_factory=DataSourceConfig)
    
    # Optional integrations (disabled by default)
    linear: LinearConfig = field(default_factory=LinearConfig)
    slack: SlackConfig = field(default_factory=SlackConfig)
    
    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        return cls(
            # Airweave (required for context search)
            airweave=AirweaveConfig(
                api_key=os.getenv("AIRWEAVE_API_KEY"),
                api_url=os.getenv("AIRWEAVE_API_URL", "https://api.airweave.ai"),
                collection_id=os.getenv("AIRWEAVE_COLLECTION_ID"),
            ),
            
            # LLM
            llm=LLMConfig(
                anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
                openai_api_key=os.getenv("OPENAI_API_KEY"),
                anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
                openai_model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            ),
            
            # Data source
            data_source=DataSourceConfig(
                source_type=os.getenv("DATA_SOURCE", "sample").lower(),
                # Azure
                azure_workspace_id=os.getenv("AZURE_LOG_ANALYTICS_WORKSPACE_ID"),
                azure_client_id=os.getenv("AZURE_LOG_ANALYTICS_CLIENT_ID"),
                azure_client_secret=os.getenv("AZURE_LOG_ANALYTICS_CLIENT_SECRET"),
                azure_tenant_id=os.getenv("AZURE_LOG_ANALYTICS_TENANT_ID"),
                # Sentry
                sentry_auth_token=os.getenv("SENTRY_AUTH_TOKEN"),
                sentry_org_slug=os.getenv("SENTRY_ORG_SLUG"),
                sentry_project_slug=os.getenv("SENTRY_PROJECT_SLUG"),
                sentry_url=os.getenv("SENTRY_URL", "https://sentry.io"),
                # Datadog
                datadog_api_key=os.getenv("DATADOG_API_KEY"),
                datadog_app_key=os.getenv("DATADOG_APP_KEY"),
                datadog_site=os.getenv("DATADOG_SITE", "datadoghq.com"),
            ),
            
            # Linear (disabled by default)
            linear=LinearConfig(
                enabled=os.getenv("LINEAR_ENABLED", "false").lower() == "true",
                api_key=os.getenv("LINEAR_API_KEY"),
                team_id=os.getenv("LINEAR_TEAM_ID"),
            ),
            
            # Slack (disabled by default)
            slack=SlackConfig(
                enabled=os.getenv("SLACK_ENABLED", "false").lower() == "true",
                api_key=os.getenv("SLACK_BOT_TOKEN"),
                channel_id=os.getenv("SLACK_CHANNEL_ID"),
                signing_secret=os.getenv("SLACK_SIGNING_SECRET"),
            ),
        )
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get configuration status for API/UI.
        
        Returns dict showing what's configured and active.
        """
        return {
            "airweave": {
                "configured": self.airweave.is_configured,
                "collection_id": self.airweave.collection_id[:8] + "..." if self.airweave.collection_id else None,
            },
            "llm": {
                "configured": self.llm.is_configured,
                "provider": self.llm.provider,
                "model": self.llm.model,
            },
            "data_source": {
                "type": self.data_source.source_type,
                "available": {
                    "sample": True,  # Always available
                    "azure": self.data_source.azure_configured,
                    "sentry": self.data_source.sentry_configured,
                    "datadog": self.data_source.datadog_configured,
                },
            },
            "integrations": {
                "linear": {
                    "enabled": self.linear.enabled,
                    "configured": self.linear.is_configured,
                    "mode": "live" if self.linear.is_configured else "preview",
                },
                "slack": {
                    "enabled": self.slack.enabled,
                    "configured": self.slack.is_configured,
                    "mode": "live" if self.slack.is_configured else "preview",
                },
            },
        }


# Cached config instance
@lru_cache(maxsize=1)
def get_config() -> Config:
    """
    Get the application configuration.
    
    Loads from environment on first call, then returns cached instance.
    """
    return Config.from_env()


def reload_config() -> Config:
    """Force reload configuration from environment."""
    get_config.cache_clear()
    return get_config()
