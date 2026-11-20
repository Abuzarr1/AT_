"""LangGraph pipeline: extract -> validate -> (retry extract | route + draft).

Human approval happens after the graph, in the UI: the graph never sends anything.
"""
from __future__ import annotations

from typing import Callable, List, Optional, TypedDict

from langgraph.graph import END, StateGraph

import config
from extractor import extract_items
from rfq_drafter import build_drafts
from schemas import LineItem, RFQDraft, RFQMeta
from suppliers import Supplier, load_suppliers
from validation import needs_retry, validate_items


class AgentState(TypedDict, total=False):
    raw_text: str
    items: List[LineItem]
    meta: RFQMeta
    notes: Optional[str]
    issues: List[str]
    attempts: int
    drafts: List[RFQDraft]
    warnings: List[str]


def build_graph(
    extract_fn: Optional[Callable] = None,
    suppliers: Optional[dict[str, Supplier]] = None,
    banned_terms: Optional[list[str]] = None,
    sender_name: str = config.SENDER_NAME,
    company: str = config.SENDER_COMPANY,
):
    extract_fn = extract_fn or extract_items
    suppliers = suppliers if suppliers is not None else load_suppliers()
    banned = banned_terms if banned_terms is not None else config.load_banned_terms()

    def extract_node(state: AgentState) -> AgentState:
        attempts = state.get("attempts", 0)
        feedback = None
        if attempts > 0:
            feedback = "; ".join(state.get("issues", [])) or "No line items were found in the previous attempt."
        result = extract_fn(state["raw_text"], feedback)
        return {"items": result.items, "meta": result.meta, "notes": result.notes, "attempts": attempts + 1}

    def validate_node(state: AgentState) -> AgentState:
        return {"issues": validate_items(state["items"])}

    def route_after_validate(state: AgentState) -> str:
        if needs_retry(state["items"]) and state["attempts"] < config.MAX_EXTRACT_ATTEMPTS:
            return "extract"
        return "draft"

    def draft_node(state: AgentState) -> AgentState:
        drafts, warnings = build_drafts(
            state["items"], suppliers, banned, sender_name, company, meta=state.get("meta")
        )
        return {"drafts": drafts, "warnings": warnings}

    graph = StateGraph(AgentState)
    graph.add_node("extract", extract_node)
    graph.add_node("validate", validate_node)
    graph.add_node("draft", draft_node)
    graph.set_entry_point("extract")
    graph.add_edge("extract", "validate")
    graph.add_conditional_edges("validate", route_after_validate, {"extract": "extract", "draft": "draft"})
    graph.add_edge("draft", END)
    return graph.compile()
