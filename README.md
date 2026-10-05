# Real estate microservices

Event-driven backend plus a React front end for a property collection. Buyers
browse listings; the write side (house CRUD) and the interaction side (likes,
view checks) never call each other on the request path - they talk over RabbitMQ.

## Shape of the system

```
React (TypeScript) --HTTP--> config (Django) --AMQP--> core (Flask)
                                  |                       |
                              houses app              HTTP back into
                                  |                    config / houses
                                MySQL                     MySQL
```

| Piece | Path | Stack | Job |
| --- | --- | --- | --- |
| config | `backend/config` | Django 5, MySQL, Docker | Settings, URL routing and DB config; installs and supervises the `houses` app; runs the AMQP producer and consumer |
| houses | `backend/config/houses` | Django | House create, list, update, delete |
| core | `backend/core` | Flask, MySQL, Docker | House likes and checks; consumes house events and calls back into config/houses |
| frontend | `frontend` | React, TypeScript, Bootstrap | Browse and like houses |

`config` owns `houses` in-process. `core` is a separate service: it consumes house
events off the bus and makes internal HTTP calls into `config` and `houses`.

## Messaging

RabbitMQ is both the broker and the event bus. Producers and consumers build the
connection from one variable (`pika.URLParameters`):

```
AQMP_URL=amqps://<user>:<password>@<host>/<vhost>
```

## Run it

Each backend service ships its own `Dockerfile` and `docker-compose.yaml`.

1. Create the env files from the templates:
   - `backend/config/.env` from `backend/config/.env.example`
   - `backend/core/.env` from `backend/core/.env.example`
2. config + houses:
   ```
   cd backend/config
   docker compose up --build
   ```
3. core:
   ```
   cd backend/core
   docker compose up --build
   ```
4. front end:
   ```
   cd frontend
   npm install
   npm start
   ```

## Config

| Variable | Files | Purpose |
| --- | --- | --- |
| `AQMP_URL` | `backend/config/.env`, `backend/core/.env` | AMQP connection string for the event bus |
| `DJANGO_SECRET_KEY` | `backend/config` | Django signing key; falls back to a dev value when unset |

No real credentials are in the repo - use the `.env.example` files.

## Property assistant (`ai/`)

A fourth service next to `config`, `core` and the front end. It answers
"find me a 3-bed under 800k near the water" over the house catalogue, and it
relaxes a filter rather than returning nothing.

```
START -> parse_criteria -> retrieve -+-> broaden -> retrieve
                                     |
                                     +-> answer -> END
```

- **Structured first** - the free-text ask is parsed into filters (city, price band, beds, must-haves)
- **Broaden once** - if too few listings survive the filters, the tightest constraint is dropped and the search re-runs
- **Says what it did** - the answer names the relaxed filter instead of hiding it
- **Models** - vLLM (`Qwen/Qwen3-32B` chat, `BAAI/bge-m3` embeddings) with Qdrant for retrieval

```
docker compose -f docker-compose.ai.yml up
```

`POST /listings` indexes the catalogue, `POST /ask` answers. See [`ai/README.md`](ai/README.md).
