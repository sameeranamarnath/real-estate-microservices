"""LangGraph property-search loop over the house catalogue.

    START -> parse_criteria -> retrieve -+-> broaden -> retrieve
                                         |
                                         +-> answer -> END

Exact filtering on a real catalogue returns empty sets constantly. Rather than
answer "nothing found", the graph drops the tightest constraint once, re-searches,
and says in the answer which filter it relaxed.
"""

import json
import re
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from core import chat_model, get_settings, search_listings


class SearchState(TypedDict, total=False):
    ask: str
    criteria: dict[str, Any]
    relaxations: list[str]
    pool: list[dict[str, Any]]
    results: list[dict[str, Any]]
    broaden_steps: int
    answer: str


def _json_block(raw: str) -> Any:
    span = re.search(r"(\{.*\})", raw.strip(), re.S)
    if not span:
        return None
    try:
        return json.loads(span.group(1))
    except json.JSONDecodeError:
        return None


def parse_criteria(state: SearchState) -> dict[str, Any]:
    prompt = (
        "Extract house search criteria. Reply with JSON only:\n"
        '{"city": string|null, "min_price": number|null, "max_price": number|null,'
        ' "min_beds": number|null, "must_have": [string]}\n'
        "Use null when the request does not say.\n\n"
        f"Request: {state['ask']}"
    )
    data = _json_block(str(chat_model(max_tokens=300).invoke(prompt).content)) or {}
    return {"criteria": data, "relaxations": [], "broaden_steps": 0}


def _matches(listing: dict[str, Any], criteria: dict[str, Any]) -> bool:
    city = criteria.get("city")
    if city and str(listing.get("city", "")).lower() != str(city).lower():
        return False
    price = listing.get("price")
    if price:
        if criteria.get("max_price") and float(price) > float(criteria["max_price"]):
            return False
        if criteria.get("min_price") and float(price) < float(criteria["min_price"]):
            return False
    beds = listing.get("beds")
    return not (beds and criteria.get("min_beds") and int(beds) < int(criteria["min_beds"]))


def retrieve(state: SearchState) -> dict[str, Any]:
    pool = search_listings(state["ask"])
    criteria = state.get("criteria", {})
    return {"pool": pool, "results": [h for h in pool if _matches(h, criteria)]}


def broaden(state: SearchState) -> dict[str, Any]:
    criteria = dict(state.get("criteria", {}))
    relaxed: list[str] = []
    if criteria.get("min_beds"):
        new = max(1, int(criteria["min_beds"]) - 1)
        relaxed.append(f"min_beds {criteria['min_beds']} -> {new}")
        criteria["min_beds"] = new
    elif criteria.get("max_price"):
        new = int(float(criteria["max_price"]) * 1.15)
        relaxed.append(f"max_price {criteria['max_price']} -> {new}")
        criteria["max_price"] = new
    elif criteria.get("city"):
        relaxed.append(f"dropped city filter ({criteria['city']})")
        criteria["city"] = None
    return {
        "criteria": criteria,
        "relaxations": list(state.get("relaxations", [])) + relaxed,
        "broaden_steps": state.get("broaden_steps", 0) + 1,
    }


def answer(state: SearchState) -> dict[str, Any]:
    results = state.get("results", [])[:6]
    if not results:
        return {"answer": "No listings matched, even after relaxing the filters."}
    compact = [
        {k: r.get(k) for k in ("title", "city", "price", "beds", "baths", "sqft")} for r in results
    ]
    relaxed = "; ".join(state.get("relaxations", [])) or "none"
    prompt = (
        "Recommend from these listings. Lead with the single best match and say why. "
        "When there are two or more, add a short comparison table. State plainly "
        "which filters were relaxed. Do not invent listings.\n\n"
        f"Request: {state['ask']}\nRelaxed filters: {relaxed}\nListings: {compact}"
    )
    return {"answer": str(chat_model().invoke(prompt).content).strip()}


def _after_retrieve(state: SearchState) -> Literal["broaden", "answer"]:
    s = get_settings()
    if len(state.get("results", [])) >= s.min_results:
        return "answer"
    if state.get("broaden_steps", 0) >= s.max_broaden_steps:
        return "answer"
    return "broaden"


def build_graph():
    g = StateGraph(SearchState)
    g.add_node("parse_criteria", parse_criteria)
    g.add_node("retrieve", retrieve)
    g.add_node("broaden", broaden)
    g.add_node("answer", answer)

    g.add_edge(START, "parse_criteria")
    g.add_edge("parse_criteria", "retrieve")
    g.add_conditional_edges("retrieve", _after_retrieve, {"broaden": "broaden", "answer": "answer"})
    g.add_edge("broaden", "retrieve")
    g.add_edge("answer", END)
    return g.compile()


APP = build_graph()


def ask(question: str) -> SearchState:
    return APP.invoke({"ask": question})
