"""Keep the test suite hermetic: no real Foundry/Azure credentials leak in from a
local .env, so tests use the mock LLM + no-op RAG store and never hit the network.
"""
import pytest

from backend.app import config, rag

_EXTERNAL_VARS = (
    "FOUNDRY_RESPONSES_URL",
    "FOUNDRY_API_KEY",
    "FOUNDRY_PROJECT",
    "FOUNDRY_MODEL",
    "FOUNDRY_EMBEDDING_MODEL",
    "FOUNDRY_EMBEDDINGS_URL",
    "AZURE_SEARCH_ENDPOINT",
    "AZURE_SEARCH_KEY",
    "AZURE_SEARCH_INDEX",
    "DAG_WEB_SEARCH",
    "DAG_BACKEND_URL",
    "DAG_DATA_DIR",
)


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch):
    for var in _EXTERNAL_VARS:
        monkeypatch.delenv(var, raising=False)
    config.get_settings.cache_clear()
    rag.get_rag_store.cache_clear()
    yield
    config.get_settings.cache_clear()
    rag.get_rag_store.cache_clear()
