"""HTTP surface for the property assistant."""

import json
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core import get_settings, index_listings, search_listings
from graph import APP, ask

api = FastAPI(title="property assistant", version="1.0.0")


class Listing(BaseModel):
    title: str | None = None
    city: str | None = None
    price: float | None = None
    beds: int | None = None
    baths: float | None = None
    sqft: int | None = None
    description: str | None = None


class ListingsRequest(BaseModel):
    listings: list[Listing]


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@api.get("/health")
def health() -> dict[str, Any]:
    s = get_settings()
    return {
        "status": "ok",
        "llm_model": s.llm_model,
        "embed_model": s.embed_model,
        "collection": s.qdrant_collection,
    }


@api.post("/listings")
def add_listings(req: ListingsRequest) -> dict[str, int]:
    payload = [
        {k: v for k, v in item.model_dump().items() if v is not None}
        for item in req.listings
    ]
    return {"indexed": index_listings(payload)}


@api.post("/ask")
def ask_endpoint(req: AskRequest) -> dict[str, Any]:
    result = ask(req.question)
    return {
        "answer": result.get("answer", ""),
        "criteria": result.get("criteria", {}),
        "relaxed": result.get("relaxations", []),
        "matches": [
            {k: r.get(k) for k in ("title", "city", "price", "beds", "baths", "sqft")}
            for r in result.get("results", [])
        ],
    }


@api.post("/ask/stream")
async def ask_stream(req: AskRequest) -> StreamingResponse:
    async def events() -> AsyncIterator[str]:
        state: dict[str, Any] = {"ask": req.question}
        for step in APP.stream(state):
            for node, update in step.items():
                yield f"event: node\ndata: {json.dumps({'node': node, 'update': _safe(update)})}\n\n"
                state.update(update)
        yield f"event: done\ndata: {json.dumps(_safe(state))}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


def _safe(d: dict[str, Any]) -> dict[str, Any]:
    """The retrieval pool is the whole result set; only the filtered matches matter."""
    out = {k: v for k, v in d.items() if k != "pool"}
    if "results" in out:
        out["results"] = [
            {k: r.get(k) for k in ("title", "city", "price", "beds")} for r in out["results"]
        ]
    return out


@api.get("/search")
def quick_search(q: str) -> dict[str, Any]:
    return {"hits": search_listings(q)}
