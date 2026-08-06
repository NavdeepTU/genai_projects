from typing import TYPE_CHECKING, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.models.document import Chunk

if TYPE_CHECKING:
    from app.services.retrieval_service import RetrievalService

MAX_RETRIES = 1


class QueryState(TypedDict):
    """The data that flows between steps of the query pipeline.

    LangGraph passes this dict through every node and merges each
    node's return value into it, so a node only needs to return the
    fields it actually changed.
    """

    original_question: str
    question: str
    candidates: list[Chunk]
    reranked_chunks: list[Chunk]
    top_relevance_score: float
    reranker_unavailable: bool
    retry_count: int
    graph_context: list[str]
    answer: str


def build_query_graph(service: "RetrievalService") -> CompiledStateGraph:
    """Wire the query pipeline's steps into a graph and compile it.

    Each node is a bound method on the given RetrievalService, so
    nodes can reach its already-hardened search/rerank helpers and its
    request-scoped database session — the graph itself holds no state
    of its own beyond how the steps connect.
    """
    graph = StateGraph(QueryState)

    graph.add_node("retrieve", service._retrieve_node)
    graph.add_node("rerank", service._rerank_node)
    graph.add_node("rewrite_query", service._rewrite_node)
    graph.add_node("graph_context", service._graph_context_node)
    graph.add_node("generate", service._generate_node)

    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "rerank")
    graph.add_conditional_edges(
        "rerank",
        service._should_retry,
        {"rewrite": "rewrite_query", "generate": "graph_context"},
    )
    graph.add_edge("rewrite_query", "retrieve")
    graph.add_edge("graph_context", "generate")
    graph.add_edge("generate", END)

    return graph.compile()
