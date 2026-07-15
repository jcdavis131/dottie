"""Core context - loads generic settings, local-first only"""
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field

class BBSettings(BaseSettings):
    # Paths
    home_dir: Path = Field(default_factory=lambda: Path.home())
    workspace_root: Path = Field(default_factory=lambda: Path.home() / "workspace")
    memory_file: Path = Field(default_factory=lambda: Path.home() / "MEMORY.md")
    
    # Generic features - local-first, tools/services/agents only
    ollama_url: str = "http://host.docker.internal:11434"
    mcp_port: int = 8787
    
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
