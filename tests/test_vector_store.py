"""Tests for vector strategy memory retrieval."""

import asyncio
from collections import deque

from aetos.memory.vector_store import (
    EMBEDDING_SCHEMA,
    StrategyVectorStore,
    cosine_similarity,
    embed_strategy_case,
)
from aetos.state import Strategy


def test_cosine_similarity_identical_vectors():
    assert round(cosine_similarity([1.0, 2.0], [1.0, 2.0]), 6) == 1.0


def test_embed_strategy_case_changes_with_request(sample_state):
    base = embed_strategy_case(sample_state, request_text="optimize")
    other = embed_strategy_case(sample_state, request_text="conservative")
    assert base != other


def test_embed_strategy_case_ignores_reward_for_retrieval(sample_state):
    base = embed_strategy_case(sample_state, request_text="market arbitrage", reward=1.0)
    other = embed_strategy_case(sample_state, request_text="market arbitrage", reward=99.0)
    assert base == other


def test_vector_store_returns_top_match(sample_state):
    store = StrategyVectorStore()
    s1 = Strategy(id="s1", bid=1.0, metadata={"mode": "market_arbitrage"})
    s2 = Strategy(id="s2", bid=0.5, metadata={"mode": "conservative"})

    asyncio.run(
        store.add_memory(
            episode_id="ep-1",
            source="test",
            state=sample_state,
            strategy=s1,
            reward=1.0,
            selected=True,
            reward_decomposition={},
        )
    )
    alt_state = sample_state.model_copy(deep=True)
    alt_state.ess_soc = 0.1
    asyncio.run(
        store.add_memory(
            episode_id="ep-2",
            source="test",
            state=alt_state,
            strategy=s2,
            reward=0.5,
            selected=True,
            reward_decomposition={},
        )
    )

    results = asyncio.run(store.search(state=sample_state, request_text="market arbitrage", top_k=1))

    assert len(results) == 1
    assert results[0]["strategy_id"] == "s1"


def test_vector_store_skips_legacy_embedding_schema(sample_state):
    store = StrategyVectorStore()
    current = embed_strategy_case(sample_state, request_text="market arbitrage")

    store._memories = deque(
        [
            {
                "id": "legacy",
                "strategy_id": "legacy-strategy",
                "selected": True,
                "reward": 9.0,
                "embedding": current,
                "embedding_schema": "legacy_v1",
            },
            {
                "id": "current",
                "strategy_id": "current-strategy",
                "selected": True,
                "reward": 1.0,
                "embedding": current,
                "embedding_schema": EMBEDDING_SCHEMA,
            },
        ],
        maxlen=2000,
    )

    results = asyncio.run(store.search(state=sample_state, request_text="market arbitrage", top_k=5))

    assert [item["strategy_id"] for item in results] == ["current-strategy"]
