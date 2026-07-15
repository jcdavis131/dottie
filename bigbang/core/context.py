"""Core context - loads MEMORY.md, config, env"""
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field
import os

class BBSettings(BaseSettings):
    # Paths
    home_dir: Path = Field(default_factory=lambda: Path.home())
    workspace_root: Path = Field(default_factory=lambda: Path.home() / "workspace")
    memory_file: Path = Field(default_factory=lambda: Path.home() / "MEMORY.md")
    
    # Feature flags - local-first only
    plaid_enabled: bool = True
    gmail_enabled: bool = True
    ollama_url: str = "http://host.docker.internal:11434"
    
    # Finance defaults from user's canonical
    emergency_target: int = 66000
    monthly_burn: int = 11000
    fed_tax_rate: float = 0.37
    
    # Solo disclaimer
    employer_isolation: bool = True
    
    class Config:
        env_file = ".env"
        env_prefix = "BB_"

settings = BBSettings()

def get_context():
    """Load lightweight context for CLI commands"""
    ctx = {
        "settings": settings,
        "memory_exists": settings.memory_file.exists(),
    }
    return ctx
