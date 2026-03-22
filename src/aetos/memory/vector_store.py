"""Vector memory for strategy retrieval backed by pgvector.

Embedding strategy
------------------
* If ``AZURE_OPENAI_EMBEDDING_DEPLOYMENT`` is configured the store calls the
  Azure OpenAI Embeddings API and produces dense semantic vectors (default
  1536-dim for text-embedding-ada-002 / text-embedding-3-small).
* Otherwise it falls back to a lightweight numeric feature vector derived
  directly from ``EnergyState`` fields, padded to ``vector_embedding_dim``.

Search strategy
---------------
* Primary: pgvector ``<=>`` cosine-distance ANN via the HNSW index that
  ``db/session.py`` creates at startup.  Only the top-k rows are fetched from
  the DB — no Python-side re-ranking needed.
* Fallback: if the DB is unavailable the in-memory ``deque`` is searched with
  the pure-Python cosine similarity used before pgvector was added.
"""

from __future__ import annotations

import logging
import math
import re
import threading
import uuid
from hashlib import blake2b
from collections import Counter, deque
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from ..config import settings
from ..state import EnergyState, Strategy

logger = logging.getLogger(__name__)

TEXT_DIM = 12
EMBEDDING_SCHEMA = "state_text_v2"
_embed_client = None
_embed_client_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------

def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def summarize_state(state: EnergyState) -> dict[str, float]:
    return {
        "avg_price": round(_avg(state.price), 6),
        "max_price": round(max(state.price, default=0.0), 6),
        "avg_load": round(_avg(state.load), 6),
        "max_load": round(max(state.load, default=0.0), 6),
        "avg_generation": round(_avg(state.generation), 6),
        "max_generation": round(max(state.generation, default=0.0), 6),
        "ess_soc": round(state.ess_soc, 6),
        "export_limit": round(state.constraints.export_limit, 6),
        "soc_min": round(state.constraints.soc_min, 6),
        "soc_max": round(state.constraints.soc_max, 6),
    }


def _text_features(text_input: str) -> list[float]:
    vec = [0.0] * TEXT_DIM
    tokens = re.findall(r"[a-zA-Z0-9_]+", text_input.lower())
    for token, count in Counter(tokens).items():
        digest = blake2b(token.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(digest, "big") % TEXT_DIM
        vec[idx] += float(count)
    return vec


def _fallback_embedding(
    state: EnergyState,
    *,
    strategy: Strategy | None = None,
    reward: float = 0.0,
    request_text: str = "",
) -> list[float]:
    """State + text fallback vector aligned between stored memories and queries."""
    base = summarize_state(state)
    vec = [
        base["avg_price"],
        base["max_price"],
        base["avg_load"],
        base["max_load"],
        base["avg_generation"],
        base["max_generation"],
        base["ess_soc"],
        base["export_limit"],
        base["soc_min"],
        base["soc_max"],
    ]
    mode = ""
    if strategy is not None:
        mode = strategy.metadata.get("mode", "")
    text_input = " ".join(part for part in [mode, request_text] if part)
    vec.extend(_text_features(text_input))
    return [round(float(v), 8) for v in vec]


def _pad_to_dim(vec: list[float], dim: int) -> list[float]:
    """Pad with zeros or truncate so the vector matches the configured dimension."""
    if len(vec) == dim:
        return vec
    if len(vec) > dim:
        return vec[:dim]
    return vec + [0.0] * (dim - len(vec))


def _get_azure_embed_client():
    """Return a shared AsyncAzureOpenAI client (created once)."""
    global _embed_client
    if _embed_client is None:
        with _embed_client_lock:
            if _embed_client is None:
                from openai import AsyncAzureOpenAI

                _embed_client = AsyncAzureOpenAI(
                    azure_endpoint=settings.azure_openai_endpoint,
                    api_key=settings.azure_openai_api_key,
                    api_version=settings.azure_openai_api_version,
                )
    return _embed_client


def _build_embedding_text(state: EnergyState, request_text: str) -> str:
    """Build a compact natural-language description of the state for embedding."""
    s = summarize_state(state)
    parts = [
        f"avg_price={s['avg_price']:.4f}",
        f"max_price={s['max_price']:.4f}",
        f"avg_load={s['avg_load']:.2f}",
        f"avg_gen={s['avg_generation']:.2f}",
        f"soc={s['ess_soc']:.2f}",
        f"export_limit={s['export_limit']:.1f}",
    ]
    base = "EnergyState: " + " ".join(parts)
    return (base + " " + request_text).strip() if request_text else base


async def _embed(
    state: EnergyState,
    *,
    strategy: Strategy | None = None,
    reward: float = 0.0,
    request_text: str = "",
) -> list[float]:
    """Return the embedding vector, using Azure OpenAI when configured."""
    dim = settings.vector_embedding_dim

    if settings.azure_openai_embedding_deployment and settings.azure_openai_endpoint:
        try:
            client = _get_azure_embed_client()
            text_input = _build_embedding_text(state, request_text)
            response = await client.embeddings.create(
                input=text_input,
                model=settings.azure_openai_embedding_deployment,
            )
            vec = response.data[0].embedding
            return _pad_to_dim(list(vec), dim)
        except Exception:
            logger.warning(
                "Azure OpenAI embedding failed; falling back to numeric features",
                exc_info=True,
            )

    numeric = _fallback_embedding(
        state,
        strategy=strategy,
        reward=reward,
        request_text=request_text,
    )
    return _pad_to_dim(numeric, dim)


# kept for backward-compat (imported by tests / agents/strategy.py via old name)
def embed_strategy_case(
    state: EnergyState,
    *,
    strategy: Strategy | None = None,
    reward: float = 0.0,
    request_text: str = "",
) -> list[float]:
    return _pad_to_dim(
        _fallback_embedding(
            state,
            strategy=strategy,
            reward=reward,
            request_text=request_text,
        ),
        settings.vector_embedding_dim,
    )


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# Vector store
# ---------------------------------------------------------------------------

class StrategyVectorStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._memories: deque[dict[str, Any]] = deque(maxlen=2000)

    async def add_memory(
        self,
        *,
        episode_id: str | None,
        source: str,
        state: EnergyState,
        strategy: Strategy,
        reward: float,
        selected: bool,
        reward_decomposition: dict[str, Any] | None = None,
    ) -> None:
        embedding = await _embed(
            state,
            strategy=strategy,
            reward=reward,
            request_text=strategy.metadata.get("mode", ""),
        )
        record = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "episode_id": episode_id,
            "strategy_id": strategy.id,
            "mode": strategy.metadata.get("mode", "unknown"),
            "source": source,
            "selected": selected,
            "reward": float(reward),
            "state_summary": summarize_state(state),
            "strategy": strategy.model_dump(),
            "reward_decomposition": reward_decomposition or {},
            "embedding_schema": EMBEDDING_SCHEMA,
            "embedding": embedding,
        }

        with self._lock:
            self._memories.appendleft(record)

        try:
            from ..db.models import StrategyMemory
            from ..db.session import AsyncSessionLocal

            if AsyncSessionLocal is None:
                return

            async with AsyncSessionLocal() as session:
                session.add(
                    StrategyMemory(
                        id=record["id"],
                        episode_id=record["episode_id"],
                        strategy_id=record["strategy_id"],
                        mode=record["mode"],
                        source=record["source"],
                        selected=record["selected"],
                        reward=record["reward"],
                        state_summary=record["state_summary"],
                        strategy=record["strategy"],
                        reward_decomposition=record["reward_decomposition"],
                        embedding_schema=record["embedding_schema"],
                        embedding=embedding,
                    )
                )
                await session.commit()
        except Exception:
            logger.debug("vector store DB write failed", exc_info=True)

    async def search(
        self,
        *,
        state: EnergyState,
        request_text: str = "",
        top_k: int | None = None,
        selected_only: bool = False,
    ) -> list[dict[str, Any]]:
        top_k = top_k or settings.vector_memory_top_k
        query_vec = await _embed(state, request_text=request_text)

        # --- primary: pgvector ANN search via HNSW index ---
        db_results = await self._search_pgvector(
            query_vec=query_vec,
            top_k=top_k,
            selected_only=selected_only,
        )
        if db_results is not None:
            return db_results

        # --- fallback: in-memory cosine similarity ---
        return self._search_memory(query_vec=query_vec, top_k=top_k, selected_only=selected_only)

    async def _search_pgvector(
        self,
        *,
        query_vec: list[float],
        top_k: int,
        selected_only: bool,
    ) -> list[dict[str, Any]] | None:
        """Search using pgvector's ``<=>`` cosine-distance operator.

        Returns a list of match dicts, or *None* if the DB is unavailable.
        The HNSW index makes this O(log n) instead of a full table scan.
        """
        try:
            from ..db.models import StrategyMemory
            from ..db.session import AsyncSessionLocal

            if AsyncSessionLocal is None:
                return None

            async with AsyncSessionLocal() as session:
                stmt = (
                    select(
                        StrategyMemory,
                        (1 - StrategyMemory.embedding.cosine_distance(query_vec)).label("score"),
                    )
                    .where(StrategyMemory.embedding_schema == EMBEDDING_SCHEMA)
                    .order_by(StrategyMemory.embedding.cosine_distance(query_vec))
                    .limit(top_k)
                )
                if selected_only:
                    stmt = stmt.where(StrategyMemory.selected.is_(True))

                rows = (await session.execute(stmt)).all()
                return [
                    {
                        "id": row.StrategyMemory.id,
                        "timestamp": row.StrategyMemory.timestamp.isoformat(),
                        "episode_id": row.StrategyMemory.episode_id,
                        "strategy_id": row.StrategyMemory.strategy_id,
                        "mode": row.StrategyMemory.mode,
                        "source": row.StrategyMemory.source,
                        "selected": row.StrategyMemory.selected,
                        "reward": row.StrategyMemory.reward,
                        "state_summary": row.StrategyMemory.state_summary,
                        "strategy": row.StrategyMemory.strategy,
                        "reward_decomposition": row.StrategyMemory.reward_decomposition,
                        "score": round(float(row.score), 6),
                    }
                    for row in rows
                ]
        except Exception:
            logger.debug("pgvector search failed; falling back to in-memory", exc_info=True)
            return None

    def _search_memory(
        self,
        *,
        query_vec: list[float],
        top_k: int,
        selected_only: bool,
    ) -> list[dict[str, Any]]:
        """Pure-Python cosine similarity over the in-memory deque (fallback)."""
        with self._lock:
            records = list(self._memories)
        records = [r for r in records if r.get("embedding_schema") == EMBEDDING_SCHEMA]
        if selected_only:
            records = [r for r in records if r.get("selected")]
        records = records[: settings.vector_memory_candidate_limit]

        scored = [
            {**r, "score": round(cosine_similarity(query_vec, r.get("embedding", [])), 6)}
            for r in records
        ]
        scored.sort(key=lambda item: (item["score"], item.get("reward", 0.0)), reverse=True)
        return scored[:top_k]

    def format_context(self, records: list[dict[str, Any]]) -> str:
        if not records:
            return "No similar strategy memories found."
        lines = []
        for idx, record in enumerate(records, start=1):
            summary = record.get("state_summary", {})
            strategy = record.get("strategy", {})
            lines.append(
                f"{idx}. mode={record.get('mode', '?')} score={record.get('score', 0):.3f} "
                f"reward={record.get('reward', 0):.4f} "
                f"soc={summary.get('ess_soc', 0):.2f} avg_price={summary.get('avg_price', 0):.4f} "
                f"market_qty={strategy.get('market', {}).get('quantity', 0):.2f}"
            )
        return "\n".join(lines)


vector_store = StrategyVectorStore()
