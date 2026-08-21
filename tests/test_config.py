"""Tests for Settings and configuration loading."""

from ragdoll.config import Settings


def test_default_config():
    s = Settings()
    assert s.github_url == "https://api.github.com"
    assert s.ollama_host == "http://localhost:11434"
    assert s.embed_model == "nomic-embed-text"


def test_github_server_config():
    s = Settings(
        github_url="https://api.github.com",
        github_token="global_token",
        github_servers={
            "enterprise": {
                "url": "https://github.internal/api/v3",
                "token": "ent_token",
            }
        },
    )
    cfg = s.get_github_config()
    assert cfg["url"] == "https://api.github.com"
    assert cfg["token"] == "global_token"

    ent_cfg = s.get_github_config("enterprise")
    assert ent_cfg["url"] == "https://github.internal/api/v3"
    assert ent_cfg["token"] == "ent_token"

    fallback = s.get_github_config("unknown")
    assert fallback["url"] == "https://api.github.com"
