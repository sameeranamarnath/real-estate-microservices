# Property assistant service

A fourth service alongside `config` (Django), `core` (Flask) and the React front
end. It answers "find me a 3-bed under 800k near the water" style questions over
the house catalogue, and it will relax constraints rather than return nothing.

## Graph

```
START -> parse_criteria -> retrieve -> assess -+-> broaden -> retrieve
                                                |
                                                +-> answer -> END
```

| Node | What it does |
| --- | --- |
| `parse_criteria` | turns the free-text ask into structured filters (city, price band, beds, must-haves) |
| `retrieve` | Qdrant vector search over listing descriptions |
| `assess` | applies the hard filters; if too few survive, it drops the tightest one and re-searches once |
| `broaden` | records which constraint was relaxed so the answer can say so |
| `answer` | recommends the best matches, with a comparison table when there are two or more |

The broaden-once step matters: exact filtering on a real catalogue returns empty
sets constantly, and an empty answer is worse than a slightly wider one that
admits what it changed.

## Stack

- LangGraph for the loop
- vLLM serving `Qwen/Qwen3-32B` (chat) and `BAAI/bge-m3` (embeddings)
- Qdrant for listing retrieval
- FastAPI + SSE; designed to sit behind the existing Docker network

## Run

```
docker compose -f docker-compose.ai.yml up
```

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | liveness and resolved model names |
| `POST` | `/listings` | bulk-index listings into Qdrant |
| `POST` | `/ask` | natural-language property search |
| `POST` | `/ask/stream` | same, as SSE per graph node |
| `GET` | `/search?q=` | retrieval-only debug view |

## Note

Listings are indexed through `POST /listings`, so the assistant does not need
direct database access - the `houses` service stays the owner of the data.
