"""
Continuous Double Auction (CDA) – negotiation layer.

In the full multi-agent version each agent submits a bid (buy) or ask
(sell) order.  In this single-system implementation the CDA acts as a
*strategy selection market*: each strategy's ``bid`` field represents
the expected value it offers (the "buy-side" willingness-to-pay), and
the market selects the top-N winners that clear at the system's
"minimum acceptable reward" threshold.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..state import Strategy

logger = logging.getLogger(__name__)


@dataclass
class OrderBook:
    """Minimal order-book that records auction outcomes."""

    rounds: list[dict] = field(default_factory=list)

    def record(self, round_data: dict) -> None:
        self.rounds.append(round_data)

    @property
    def last_clearing_price(self) -> float:
        return self.rounds[-1]["clearing_price"] if self.rounds else 0.0


class CDAMarket:
    """
    Continuous Double Auction market.

    ``auction`` takes a list of strategies (bids), determines the
    clearing price (median bid), and returns the strategies whose bid
    meets or exceeds the clearing price.  This ensures multiple
    "winning" candidates are forwarded to the MetaCritic for final
    selection rather than hard-coding argmax here.
    """

    def __init__(self, min_candidates: int = 1) -> None:
        self.min_candidates = min_candidates
        self.order_book = OrderBook()

    # ------------------------------------------------------------------
    def auction(self, strategies: list[Strategy]) -> list[Strategy]:
        """Run a single CDA round and return cleared (winning) strategies.

        Args:
            strategies: Optimised candidate strategies with bid values.

        Returns:
            List of strategies at or above the clearing price.
            Guaranteed to contain at least ``min_candidates`` entries.
        """
        if not strategies:
            raise ValueError("CDAMarket.auction: no strategies provided")

        bids = sorted(strategies, key=lambda s: s.bid, reverse=True)

        # Clearing price = median bid (simple market-clearing rule)
        mid = len(bids) // 2
        clearing_price = bids[mid].bid if bids else 0.0

        winners = [s for s in bids if s.bid >= clearing_price]

        # Guarantee at least min_candidates pass through
        if len(winners) < self.min_candidates:
            winners = bids[: self.min_candidates]

        self.order_book.record(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "n_bids": len(bids),
                "clearing_price": clearing_price,
                "n_winners": len(winners),
                "best_bid": bids[0].bid,
                "worst_bid": bids[-1].bid,
            }
        )

        logger.info(
            "CDA round: clearing=%.4f  winners=%d/%d",
            clearing_price,
            len(winners),
            len(bids),
        )
        return winners

    # ------------------------------------------------------------------
    @property
    def history(self) -> list[dict]:
        return self.order_book.rounds
