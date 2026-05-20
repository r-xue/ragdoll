"""Configuration management for Ragdoll.

Settings are resolved from four layers, highest priority first:

1. **Environment variables** (``RAGDOLL_*``)
   Ephemeral overrides, great for CI or one-off runs.
   Example: ``RAGDOLL_CHAT_MODEL=deepseek-r1:32b ragdoll chat``

2. **Working-directory config** (per-project)
   - ``./ragdoll.toml``  — project-level settings (safe to commit)
   - ``./.env``          — project-level secrets  (git-ignored)

3. **User config** (``~/.ragdoll/config.toml``)
   Personal defaults shared across all projects.

4. **Package defaults** (hardcoded in this file)
   Sensible fallbacks so ragdoll works out of the box.

This follows the same convention as git, pip, and npm:
most-specific scope wins.
"""

from pathlib import Path
from typing import Tuple, Type

from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

# ── Config file locations ──────────────────────────────────────────────
_USER_CONFIG = Path.home() / ".ragdoll" / "config.toml"  # layer 3
_PROJECT_CONFIG = "ragdoll.toml"                          # layer 2 (CWD-relative)


class Settings(BaseSettings):
    """Ragdoll configuration.

    All fields map to environment variables prefixed with ``RAGDOLL_``.
    For example ``RAGDOLL_CHAT_MODEL`` → ``chat_model``.

    Precedence: env vars > ./ragdoll.toml > ./.env > ~/.ragdoll/config.toml > defaults.
    """

    model_config = SettingsConfigDict(
        env_prefix="RAGDOLL_",
        env_file=".env",
        env_file_encoding="utf-8",
        toml_file=[_PROJECT_CONFIG, str(_USER_CONFIG)],
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        """Define the 4-layer config precedence.

        pydantic-settings resolves left-to-right: the first source to
        provide a value wins.
        """
        # Build two separate TOML sources so they sit at different
        # priority levels — project config (CWD) beats user config (~/).
        project_toml = TomlConfigSettingsSource(
            settings_cls,
            toml_file=Path(_PROJECT_CONFIG),
        )
        user_toml = TomlConfigSettingsSource(
            settings_cls,
            toml_file=_USER_CONFIG,
        )

        return (
            init_settings,      # 0. explicit kwargs  (programmatic)
            env_settings,       # 1. RAGDOLL_* env vars
            project_toml,       # 2a. ./ragdoll.toml  (project, non-secret)
            dotenv_settings,    # 2b. ./.env           (project, secrets)
            user_toml,          # 3. ~/.ragdoll/config.toml  (user defaults)
            # 4. package defaults are the field defaults below
        )

    # ── JIRA ───────────────────────────────────────────────────────────
    jira_url: str = "https://jira.example.com"
    jira_user: str = ""
    jira_token: str = ""
    jira_batch_size: int = 50  # issues per API request
    jira_auth_method: str = "pat"  # "pat" for Data Center, "basic" for Cloud

    # ── Ollama ─────────────────────────────────────────────────────────
    ollama_host: str = "http://localhost:11434"
    embed_model: str = "nomic-embed-text"
    chat_model: str = "gpt-oss:20b"
    temperature: float = 0.3

    # ── Storage ────────────────────────────────────────────────────────
    data_dir: Path = Path.home() / ".ragdoll" / "data"
    collection_name: str = "ragdoll"

    # ── Chunking ───────────────────────────────────────────────────────
    chunk_size: int = 1000  # characters per chunk
    chunk_overlap: int = 200  # overlap between consecutive chunks

    # ── Retrieval ──────────────────────────────────────────────────────
    top_k: int = 20  # number of chunks to retrieve

    @property
    def chroma_dir(self) -> Path:
        """Path to the ChromaDB persistent storage directory."""
        return self.data_dir / "chroma"

    def ensure_dirs(self) -> None:
        """Create data directories if they don't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.chroma_dir.mkdir(parents=True, exist_ok=True)


# Module-level singleton — importable as ``from ragdoll.config import settings``
settings = Settings()

def setup_llamaindex():
    from llama_index.core import Settings as LlamaSettings
    from llama_index.llms.ollama import Ollama
    from llama_index.embeddings.ollama import OllamaEmbedding

    # Configure global LLM and Embeddings for LlamaIndex
    LlamaSettings.llm = Ollama(
        model=settings.chat_model,
        base_url=settings.ollama_host,
        temperature=settings.temperature,
        request_timeout=600.0,
    )
    LlamaSettings.embed_model = OllamaEmbedding(
        model_name=settings.embed_model,
        base_url=settings.ollama_host,
    )
    LlamaSettings.chunk_size = settings.chunk_size
    LlamaSettings.chunk_overlap = settings.chunk_overlap

# Initialize on import
setup_llamaindex()

