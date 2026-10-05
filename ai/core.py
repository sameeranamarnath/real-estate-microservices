"""Config, model clients and Qdrant access for the property assistant.

Deploys as another service next to the Django `config`/`houses` and Flask `core`
apps. It reads the house collection (over HTTP from `houses`, or from a dump) and
keeps its own semantic index of listings, so natural-language search does not
need SQL LIKE queries.
"""

from functools import lru_cache
from typing import Any

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pydantic_settings import BaseSettings, SettingsConfigDict
from qdrant_client import QdrantClient, models


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_base_url: str = "http://vllm:8000/v1"
    llm_api_key: str = "local-vllm"
    llm_model: str = "Qwen/Qwen3-32B"

    embed_base_url: str = "http://vllm-embed:8000/v1"
    embed_model: str = "BAAI/bge-m3"
    embed_dim: int = 1024

    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "property_listings"

    # Where the house catalogue lives. `houses` is the Django app in backend/config.
    houses_api_base: str | None = None

    top_k: int = 8
    min_results: int = 3
    max_broaden_steps: int = 1


@lru_cache
def get_settings() -> Settings:
    return Settings()


def chat_model(temperature: float = 0.0, max_tokens: int = 1200) -> ChatOpenAI:
    s = get_settings()
    return ChatOpenAI(
        model=s.llm_model,
        base_url=s.llm_base_url,
        api_key=s.llm_api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        max_retries=2,
        timeout=120,
    )


def embed_model() -> OpenAIEmbeddings:
    s = get_settings()
    return OpenAIEmbeddings(
        model=s.embed_model,
        base_url=s.embed_base_url,
        api_key=s.llm_api_key,
        check_embedding_ctx_length=False,
    )


def qdrant() -> QdrantClient:
    s = get_settings()
    return QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key)


def ensure_collection() -> str:
    s = get_settings()
    c = qdrant()
    if not c.collection_exists(s.qdrant_collection):
        c.create_collection(
            collection_name=s.qdrant_collection,
            vectors_config=models.VectorParams(size=s.embed_dim, distance=models.Distance.COSINE),
        )
    return s.qdrant_collection


def _listing_text(listing: dict[str, Any]) -> str:
    bits = [
        str(listing.get("title", "")),
        str(listing.get("city", "")),
        f"{listing.get('beds', '?')} bed / {listing.get('baths', '?')} bath",
        f"{listing.get('sqft', '?')} sqft",
        f"${listing.get('price', '?')}",
        str(listing.get("description", "")),
    ]
    return " | ".join(b for b in bits if b and b != "?")


def index_listings(listings: list[dict[str, Any]]) -> int:
    if not listings:
        return 0
    collection = ensure_collection()
    vectors = embed_model().embed_documents([_listing_text(item) for item in listings])
    c = qdrant()
    start = c.count(collection_name=collection).count
    points = [
        models.PointStruct(id=start + i, vector=v, payload={**item, "text": _listing_text(item)})
        for i, (item, v) in enumerate(zip(listings, vectors, strict=False))
    ]
    c.upsert(collection_name=collection, points=points)
    return len(points)


def search_listings(query: str, top_k: int | None = None) -> list[dict[str, Any]]:
    s = get_settings()
    collection = ensure_collection()
    hits = qdrant().search(
        collection_name=collection,
        query_vector=embed_model().embed_query(query),
        limit=top_k or s.top_k,
        with_payload=True,
    )
    return [{"score": round(float(h.score), 4), **(h.payload or {})} for h in hits]
