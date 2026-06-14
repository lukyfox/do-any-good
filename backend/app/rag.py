"""RAG store: persist (anonymized profile -> completed Goody) records and
retrieve a similar one, backed by Azure AI Search (the vector engine that
Foundry IQ knowledge bases sit on).

Profiles are anonymized (no nickname/email) before storage. Matching is vector
similarity over a short profile descriptor, embedded with an Azure OpenAI
embeddings deployment. Falls back to a no-op store (NullRagStore) when Azure
Search / embeddings aren't configured, so the app runs offline.
"""
from __future__ import annotations

import random
import uuid
from typing import Protocol

import requests

from .config import Settings, get_settings
from .storage import Goody, UserProfile

EMBEDDINGS_TIMEOUT_SECONDS = 30
SEARCH_TOP_K = 5


def anonymize_profile(profile: UserProfile) -> dict:
    """Profile fields safe to store in shared RAG (drops nickname and email)."""
    return {
        "preferences": list(profile.preferences),
        "age": profile.age,
        "locality": profile.locality,
        "social_environment": profile.social_environment,
        "notes": profile.notes,
    }


def profile_text(profile: UserProfile) -> str:
    """A compact descriptor of a profile, used as the embedding/match key."""
    anon = anonymize_profile(profile)
    parts = []
    if anon["preferences"]:
        parts.append("Prefers: " + ", ".join(anon["preferences"]))
    if anon["locality"]:
        parts.append(f"Locality: {anon['locality']}")
    if anon["age"] is not None:
        parts.append(f"Age: {anon['age']}")
    if anon["social_environment"]:
        parts.append(f"Social environment: {anon['social_environment']}")
    if anon["notes"]:
        parts.append(f"Notes: {anon['notes']}")
    return " | ".join(parts) or "No profile details."


class RagStore(Protocol):
    def save(self, profile: UserProfile, goody: Goody) -> None: ...

    def find_match(self, profile: UserProfile) -> Goody | None: ...


class NullRagStore:
    """No-op store used when RAG isn't configured."""

    def save(self, profile: UserProfile, goody: Goody) -> None:
        return None

    def find_match(self, profile: UserProfile) -> Goody | None:
        return None


def _embed(text: str, settings: Settings) -> list[float]:
    headers = {"api-key": settings.foundry_api_key or "", "Content-Type": "application/json"}
    payload = {"model": settings.foundry_embedding_model, "input": text}
    response = requests.post(
        settings.embeddings_url, json=payload, headers=headers, timeout=EMBEDDINGS_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    return response.json()["data"][0]["embedding"]


class AzureSearchRagStore:
    """Azure AI Search-backed RAG store (vector similarity over profile text)."""

    def __init__(self, settings: Settings | None = None) -> None:
        from azure.core.credentials import AzureKeyCredential
        from azure.search.documents import SearchClient

        self._settings = settings or get_settings()
        s = self._settings
        self._ensure_index()
        self._client = SearchClient(
            s.azure_search_endpoint,
            s.azure_search_index,
            AzureKeyCredential(s.azure_search_key or ""),
        )

    def _ensure_index(self) -> None:
        from azure.core.credentials import AzureKeyCredential
        from azure.search.documents.indexes import SearchIndexClient
        from azure.search.documents.indexes.models import (
            HnswAlgorithmConfiguration,
            SearchableField,
            SearchField,
            SearchFieldDataType,
            SearchIndex,
            SimpleField,
            VectorSearch,
            VectorSearchProfile,
        )

        s = self._settings
        index = SearchIndex(
            name=s.azure_search_index,
            fields=[
                SimpleField(name="id", type=SearchFieldDataType.String, key=True),
                SimpleField(name="goody_json", type=SearchFieldDataType.String),
                SearchableField(name="profile_text", type=SearchFieldDataType.String),
                SearchField(
                    name="profile_vector",
                    type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                    searchable=True,
                    vector_search_dimensions=s.embedding_dimensions,
                    vector_search_profile_name="dag-prof",
                ),
            ],
            vector_search=VectorSearch(
                profiles=[
                    VectorSearchProfile(name="dag-prof", algorithm_configuration_name="dag-hnsw")
                ],
                algorithms=[HnswAlgorithmConfiguration(name="dag-hnsw")],
            ),
        )
        index_client = SearchIndexClient(
            s.azure_search_endpoint, AzureKeyCredential(s.azure_search_key or "")
        )
        index_client.create_or_update_index(index)

    def save(self, profile: UserProfile, goody: Goody) -> None:
        text = profile_text(profile)
        self._client.upload_documents(
            [
                {
                    "id": uuid.uuid4().hex,
                    "goody_json": goody.model_dump_json(),
                    "profile_text": text,
                    "profile_vector": _embed(text, self._settings),
                }
            ]
        )

    def find_match(self, profile: UserProfile) -> Goody | None:
        from azure.search.documents.models import VectorizedQuery

        vector = _embed(profile_text(profile), self._settings)
        query = VectorizedQuery(
            vector=vector, k_nearest_neighbors=SEARCH_TOP_K, fields="profile_vector"
        )
        try:
            results = list(
                self._client.search(search_text=None, vector_queries=[query], top=SEARCH_TOP_K)
            )
        except Exception:
            return None
        if not results:
            return None
        try:
            return Goody.model_validate_json(random.choice(results)["goody_json"])
        except Exception:
            return None


def get_rag_store() -> RagStore:
    """Return the Azure-backed store when configured, else a no-op store."""
    settings = get_settings()
    if settings.rag_configured:
        try:
            return AzureSearchRagStore(settings)
        except Exception:
            return NullRagStore()
    return NullRagStore()
