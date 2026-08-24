"""Tests for Settings and configuration loading."""

from ragdoll.config import Settings


def test_default_config(monkeypatch, tmp_path):
    monkeypatch.setattr("ragdoll.config._USER_CONFIG", tmp_path / "nonexistent.toml")
    s = Settings()
    assert s.github_url == "https://api.github.com"
    assert s.ollama_host == "http://localhost:11434"
    assert s.embed_model == "nomic-embed-text"


def test_jira_server_projects_config():
    s = Settings(
        jira_servers={
            "primary": {
                "url": "https://jira.primary.example.com",
                "token": "tok1",
                "projects": ["PROJA", "PROJB"],
            },
            "secondary": {
                "url": "https://jira.secondary.example.com",
                "token": "tok2",
                "projects": ["EXTA", "EXTB"],
            },
        }
    )
    pri_cfg = s.get_jira_config("primary")
    assert pri_cfg["projects"] == ["PROJA", "PROJB"]
    assert pri_cfg["url"] == "https://jira.primary.example.com"

    sec_cfg = s.get_jira_config("secondary")
    assert sec_cfg["projects"] == ["EXTA", "EXTB"]


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


def test_github_server_repos_and_default_owner():
    s = Settings(
        github_repos=[],
        github_default_owner="myorg",
        github_servers={
            "public": {
                "url": "https://api.github.com",
                "token": "tok_pub",
                "repos": ["myorg/repo1", "myorg/repo2"],
            },
            "ent": {
                "url": "https://github.internal/api/v3",
                "token": "tok_ent",
                "repos": ["internal/service"],
            },
        },
    )
    assert s.github_default_owner == "myorg"
    pub_cfg = s.get_github_config("public")
    assert pub_cfg["repos"] == ["myorg/repo1", "myorg/repo2"]
    assert pub_cfg["default_owner"] == "myorg"

    all_repos = s.get_all_github_repos()
    assert all_repos == ["myorg/repo1", "myorg/repo2", "internal/service"]


def test_chroma_settings():
    s = Settings(
        chroma_host="http://chroma.internal",
        chroma_port=8080,
        chroma_ssl=True,
        chroma_auth_token="secret-token",
    )
    assert s.chroma_host == "http://chroma.internal"
    assert s.chroma_port == 8080
    assert s.chroma_ssl is True
    assert s.chroma_auth_token == "secret-token"


def test_thinking_settings():
    s = Settings(enable_thinking=True)
    assert s.enable_thinking is True
    assert s.thinking is True

    s_off = Settings(enable_thinking=False)
    assert s_off.enable_thinking is False
    assert s_off.thinking is False
