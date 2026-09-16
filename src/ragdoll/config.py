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

from pydantic import Field

from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

# ── Config file locations ──────────────────────────────────────────────
_USER_CONFIG = Path.home() / ".ragdoll" / "config.toml"  # layer 3
_PROJECT_CONFIG = "ragdoll.toml"                          # layer 2 (CWD-relative)

# Standard browser User-Agent to prevent WAF / CDN bot flagging
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


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
    jira_servers: dict[str, dict] = Field(default_factory=dict)
    jira_url: str = "https://jira.example.com"
    jira_user: str = ""
    jira_token: str = ""
    jira_batch_size: int = 100  # issues per API request
    jira_auth_method: str = "pat"  # "pat" for Data Center, "basic" for Cloud

    def get_jira_config(
        self,
        server_name: str | None = None,
        project: str | None = None,
    ) -> dict:
        """Get the active Jira configuration.

        Resolution precedence:
        1. Explicit server_name in jira_servers.
        2. Match by project key against jira_servers[...]["projects"].
        3. Single server in jira_servers (if top-level token is not set).
        4. "default" server in jira_servers (if present).
        5. Global top-level jira_* settings.
        """
        resolved_name = server_name

        if not resolved_name and project and self.jira_servers:
            clean_proj = project.strip().upper()
            for sname, scfg in self.jira_servers.items():
                raw_projects = scfg.get("projects", [])
                if isinstance(raw_projects, str):
                    s_projects = [p.strip().upper() for p in raw_projects.split(",") if p.strip()]
                else:
                    s_projects = [str(p).strip().upper() for p in raw_projects]
                if clean_proj in s_projects:
                    resolved_name = sname
                    break

        if not resolved_name and not self.jira_token and self.jira_servers:
            if len(self.jira_servers) == 1:
                resolved_name = next(iter(self.jira_servers.keys()))
            elif "default" in self.jira_servers:
                resolved_name = "default"

        if resolved_name and resolved_name in self.jira_servers:
            cfg = self.jira_servers[resolved_name]
            return {
                "server_name": resolved_name,
                "url": cfg.get("url", self.jira_url),
                "user": cfg.get("user", self.jira_user),
                "token": cfg.get("token", self.jira_token),
                "batch_size": cfg.get("batch_size", self.jira_batch_size),
                "auth_method": cfg.get("auth_method", self.jira_auth_method),
                "projects": cfg.get("projects", []),
            }
        return {
            "server_name": "default",
            "url": self.jira_url,
            "user": self.jira_user,
            "token": self.jira_token,
            "batch_size": self.jira_batch_size,
            "auth_method": self.jira_auth_method,
            "projects": [],
        }

    # ── BITBUCKET ──────────────────────────────────────────────────────
    bitbucket_servers: dict[str, dict] = Field(default_factory=dict)
    bitbucket_url: str = "https://bitbucket.example.com"
    bitbucket_user: str = ""
    bitbucket_token: str = ""
    bitbucket_auth_method: str = "pat"  # "pat" for HTTP access token, "basic" for username/password

    def get_bitbucket_config(self, server_name: str | None = None) -> dict:
        """Get the active Bitbucket configuration."""
        if server_name and server_name in self.bitbucket_servers:
            cfg = self.bitbucket_servers[server_name]
            return {
                "url": cfg.get("url", self.bitbucket_url),
                "user": cfg.get("user", self.bitbucket_user),
                "token": cfg.get("token", self.bitbucket_token),
                "auth_method": cfg.get("auth_method", self.bitbucket_auth_method),
            }
        return {
            "url": self.bitbucket_url,
            "user": self.bitbucket_user,
            "token": self.bitbucket_token,
            "auth_method": self.bitbucket_auth_method,
        }

    # ── GITHUB ─────────────────────────────────────────────────────────
    github_servers: dict[str, dict] = Field(default_factory=dict)
    github_url: str = "https://api.github.com"
    github_token: str = ""

    github_default_owner: str = ""
    github_repos: list[str] = Field(default_factory=list)

    def get_github_config(self, server_name: str | None = None) -> dict:
        """Get the active GitHub configuration."""
        if server_name and server_name in self.github_servers:
            cfg = self.github_servers[server_name]
            return {
                "url": cfg.get("url", self.github_url),
                "token": cfg.get("token", self.github_token),
                "default_owner": cfg.get("default_owner", self.github_default_owner),
                "repos": cfg.get("repos", []),
            }
        return {
            "url": self.github_url,
            "token": self.github_token,
            "default_owner": self.github_default_owner,
            "repos": self.github_repos,
        }

    def get_all_github_repos(self) -> list[str]:
        """Get list of all tracked GitHub repositories across all servers."""
        all_repos = list(self.github_repos)
        for name, cfg in self.github_servers.items():
            repos = cfg.get("repos", [])
            if isinstance(repos, list):
                all_repos.extend(repos)
            elif isinstance(repos, str):
                all_repos.extend([r.strip() for r in repos.split(",") if r.strip()])
        return list(dict.fromkeys(all_repos))

    # ── CONFLUENCE ─────────────────────────────────────────────────────
    confluence_servers: dict[str, dict] = Field(default_factory=dict)
    confluence_url: str = "https://confluence.example.com"
    confluence_user: str = ""
    confluence_token: str = ""
    confluence_auth_method: str = "pat"  # "pat" for Data Center, "basic" for Cloud
    confluence_cookie: str = ""

    def get_confluence_config(
        self,
        server_name: str | None = None,
        space: str | None = None,
    ) -> dict:
        """Get the active Confluence configuration.

        Resolution precedence:
        1. Explicit server_name in confluence_servers.
        2. Match by space against confluence_servers[...]["spaces"].
        3. Single server in confluence_servers (if top-level token is not set).
        4. "default" server in confluence_servers (if present).
        5. Global top-level confluence_* settings.
        """
        resolved_name = server_name

        if not resolved_name and space and self.confluence_servers:
            clean_sp = space.strip().lower()
            for sname, scfg in self.confluence_servers.items():
                raw_spaces = scfg.get("spaces", [])
                if isinstance(raw_spaces, str):
                    s_spaces = [s.strip().lower() for s in raw_spaces.split(",") if s.strip()]
                else:
                    s_spaces = [str(s).strip().lower() for s in raw_spaces]
                if clean_sp in s_spaces:
                    resolved_name = sname
                    break

        if not resolved_name and not self.confluence_token and self.confluence_servers:
            if len(self.confluence_servers) == 1:
                resolved_name = next(iter(self.confluence_servers.keys()))
            elif "default" in self.confluence_servers:
                resolved_name = "default"

        if resolved_name and resolved_name in self.confluence_servers:
            cfg = self.confluence_servers[resolved_name]
            return {
                "server_name": resolved_name,
                "url": cfg.get("url", self.confluence_url),
                "user": cfg.get("user", self.confluence_user),
                "token": cfg.get("token", self.confluence_token),
                "auth_method": cfg.get("auth_method", self.confluence_auth_method),
                "cookie": cfg.get("cookie", cfg.get("cookies", self.confluence_cookie)),
                "spaces": cfg.get("spaces", []),
            }
        return {
            "server_name": "default",
            "url": self.confluence_url,
            "user": self.confluence_user,
            "token": self.confluence_token,
            "auth_method": self.confluence_auth_method,
            "cookie": self.confluence_cookie,
            "spaces": [],
        }

    # ── Ollama ─────────────────────────────────────────────────────────
    ollama_host: str = "http://localhost:11434"
    embed_model: str = "nomic-embed-text"
    chat_model: str = "gpt-oss:20b"
    temperature: float = 0.3
    enable_thinking: bool = False

    # ── Storage ────────────────────────────────────────────────────────
    data_dir: Path = Path.home() / ".ragdoll" / "data"
    collection_name: str = "ragdoll"
    chroma_host: str | None = None  # e.g., "http://chroma.internal" or "localhost" for remote server
    chroma_port: int = 8000
    chroma_ssl: bool = False
    chroma_auth_token: str | None = None
    chroma_tenant: str = "default_tenant"
    chroma_database: str = "default_database"

    # ── Chunking ───────────────────────────────────────────────────────
    chunk_size: int = 1000  # characters per chunk
    chunk_overlap: int = 200  # overlap between consecutive chunks

    # ── Retrieval ──────────────────────────────────────────────────────
    top_k: int = 5  # number of chunks to retrieve (default: 5)

    @property
    def llm_model(self) -> str:
        return self.chat_model

    @property
    def ollama_base_url(self) -> str:
        return self.ollama_host

    @property
    def thinking(self) -> bool:
        return self.enable_thinking

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


def setup_llamaindex(thinking: bool | None = None):
    from llama_index.core import Settings as LlamaSettings
    from llama_index.llms.ollama import Ollama
    from llama_index.embeddings.ollama import OllamaEmbedding

    class OllamaEmbed(OllamaEmbedding):
        """Custom OllamaEmbedding subclass using the newer /api/embed API.

        Provides batching support to avoid making one HTTP request per node,
        and enables truncate=True to prevent 'input length exceeds context length' errors.
        """

        def get_general_text_embedding(self, texts: str) -> list[float]:
            safe_texts = texts[:32000] if isinstance(texts, str) else texts
            result = self._client.embed(
                model=self.model_name,
                input=safe_texts,
                truncate=True,
                options=self.ollama_additional_kwargs,
            )
            return result.embeddings[0]

        async def aget_general_text_embedding(self, prompt: str) -> list[float]:
            safe_prompt = prompt[:32000] if isinstance(prompt, str) else prompt
            result = await self._async_client.embed(
                model=self.model_name,
                input=safe_prompt,
                truncate=True,
                options=self.ollama_additional_kwargs,
            )
            return result.embeddings[0]

        def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
            if not texts:
                return []

            # Manually truncate to 3500 chars (approx 800-1000 tokens) to safely avoid
            # Ollama's context length bug which sometimes ignores truncate=True
            safe_texts = [t[:3500] if isinstance(t, str) else t for t in texts]

            result = self._client.embed(
                model=self.model_name,
                input=safe_texts,
                truncate=True,
                options=self.ollama_additional_kwargs,
            )
            return result.embeddings

        async def _aget_text_embeddings(self, texts: list[str]) -> list[list[float]]:
            if not texts:
                return []

            safe_texts = [t[:3500] if isinstance(t, str) else t for t in texts]

            result = await self._async_client.embed(
                model=self.model_name,
                input=safe_texts,
                truncate=True,
                options=self.ollama_additional_kwargs,
            )
            return result.embeddings

    # Configure global LLM and Embeddings for LlamaIndex
    eff_thinking = settings.enable_thinking if thinking is None else thinking
    LlamaSettings.llm = Ollama(
        model=settings.chat_model,
        base_url=settings.ollama_host,
        temperature=settings.temperature,
        request_timeout=600.0,
        thinking=eff_thinking,
        additional_kwargs={"num_predict": 2048},
    )
    LlamaSettings.embed_model = OllamaEmbed(
        model_name=settings.embed_model,
        base_url=settings.ollama_host,
    )
    LlamaSettings.chunk_size = settings.chunk_size
    LlamaSettings.chunk_overlap = settings.chunk_overlap


def get_llm(thinking: bool | None = None):
    """Get an Ollama LLM instance with runtime thinking toggle support."""
    from llama_index.llms.ollama import Ollama
    eff_thinking = settings.enable_thinking if thinking is None else thinking
    return Ollama(
        model=settings.chat_model,
        base_url=settings.ollama_host,
        temperature=settings.temperature,
        request_timeout=600.0,
        thinking=eff_thinking,
        additional_kwargs={"num_predict": 2048},
    )


# Initialize on import
setup_llamaindex()
