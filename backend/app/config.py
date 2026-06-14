"""Typed application configuration loaded from environment / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the repository root (two levels up from this file), if present.
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=_ENV_PATH)


@dataclass(frozen=True)
class Settings:
    """Runtime configuration for the Do Any Good backend."""

    foundry_responses_url: str | None = None
    foundry_api_key: str | None = None
    foundry_project: str | None = None
    foundry_model: str | None = None
    web_search_enabled: bool = True
    foundry_embedding_model: str | None = None
    foundry_embeddings_url: str | None = None
    azure_search_endpoint: str | None = None
    azure_search_key: str | None = None
    azure_search_index: str = "dag-goodies"
    data_dir: str = "data"

    @property
    def foundry_configured(self) -> bool:
        """True when both a Foundry endpoint and an API key are available."""
        return bool(self.foundry_responses_url and self.foundry_api_key)

    @property
    def is_azure_openai(self) -> bool:
        """True when the endpoint points at an Azure OpenAI host."""
        url = self.foundry_responses_url or ""
        return "openai.azure.com" in url

    @property
    def embeddings_url(self) -> str:
        """Azure OpenAI embeddings endpoint (derived from the responses URL)."""
        if self.foundry_embeddings_url:
            return self.foundry_embeddings_url
        return (self.foundry_responses_url or "").replace("/responses", "/embeddings")

    @property
    def rag_configured(self) -> bool:
        """True when Azure AI Search + an embeddings deployment are available."""
        return bool(
            self.azure_search_endpoint
            and self.azure_search_key
            and self.foundry_embedding_model
            and self.foundry_api_key
            and self.embeddings_url
        )


@lru_cache
def get_settings() -> Settings:
    """Return cached settings read from the environment."""
    return Settings(
        foundry_responses_url=os.getenv("FOUNDRY_RESPONSES_URL"),
        foundry_api_key=os.getenv("FOUNDRY_API_KEY"),
        foundry_project=os.getenv("FOUNDRY_PROJECT"),
        foundry_model=os.getenv("FOUNDRY_MODEL"),
        web_search_enabled=os.getenv("DAG_WEB_SEARCH", "true").lower() != "false",
        foundry_embedding_model=os.getenv("FOUNDRY_EMBEDDING_MODEL"),
        foundry_embeddings_url=os.getenv("FOUNDRY_EMBEDDINGS_URL"),
        azure_search_endpoint=os.getenv("AZURE_SEARCH_ENDPOINT"),
        azure_search_key=os.getenv("AZURE_SEARCH_KEY"),
        azure_search_index=os.getenv("AZURE_SEARCH_INDEX", "dag-goodies"),
        data_dir=os.getenv("DAG_DATA_DIR", "data"),
    )
