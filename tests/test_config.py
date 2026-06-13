from backend.app.config import Settings, get_settings

_ALL_VARS = (
    "FOUNDRY_RESPONSES_URL",
    "FOUNDRY_API_KEY",
    "FOUNDRY_PROJECT",
    "FOUNDRY_MODEL",
    "DAG_DATA_DIR",
)


def test_defaults_when_env_absent(monkeypatch):
    for var in _ALL_VARS:
        monkeypatch.delenv(var, raising=False)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.foundry_configured is False
    assert settings.data_dir == "data"


def test_reads_env(monkeypatch):
    monkeypatch.setenv("FOUNDRY_RESPONSES_URL", "https://x.openai.azure.com/responses")
    monkeypatch.setenv("FOUNDRY_API_KEY", "secret")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.foundry_configured is True
    assert settings.is_azure_openai is True


def test_is_azure_detection():
    azure = Settings(
        foundry_responses_url="https://x.openai.azure.com/responses",
        foundry_api_key="k",
    )
    other = Settings(
        foundry_responses_url="https://foundry.example.com/responses",
        foundry_api_key="k",
    )
    assert azure.is_azure_openai is True
    assert other.is_azure_openai is False
