from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Iterable

from root_parser import split_words


_ASIN = re.compile(r"^B[A-Z0-9]{9}$", re.IGNORECASE)


@dataclass(frozen=True)
class Metrics:
    impressions: float = 0
    clicks: float = 0
    orders: float = 0
    spend: float = 0
    sales: float = 0

    def __add__(self, other: "Metrics") -> "Metrics":
        return Metrics(*(a + b for a, b in zip(self.values(), other.values())))

    def values(self) -> tuple[float, float, float, float, float]:
        return self.impressions, self.clicks, self.orders, self.spend, self.sales

    @property
    def cpa(self) -> float | None:
        return self.spend / self.orders if self.orders else None

    @property
    def acos(self) -> float | None:
        return self.spend / self.sales if self.sales else None


@dataclass(frozen=True)
class RootAggregate:
    root: str
    metrics: Metrics
    search_terms: tuple[tuple[str, Metrics], ...]


def canonical_asin(value: object) -> str | None:
    text = "" if value is None else str(value).strip()
    if not _ASIN.fullmatch(text) or not any(char.isdigit() for char in text):
        return None
    return text.upper()


def row_metrics(row: dict[str, Any]) -> Metrics:
    def value(name: str) -> float:
        try:
            return float(row.get(name) or 0)
        except (TypeError, ValueError):
            return 0.0
    return Metrics(value("impressions"), value("clicks"), value("orders"), value("spends"), value("sales"))


def aggregate_rows(rows: Iterable[dict[str, Any]]) -> dict[str, RootAggregate]:
    root_metrics: OrderedDict[str, Metrics] = OrderedDict()
    root_terms: OrderedDict[str, OrderedDict[str, Metrics]] = OrderedDict()
    for row in rows:
        term = str(row.get("query") or "").strip()
        if not term:
            continue
        metrics = row_metrics(row)
        roots = [canonical_asin(term)] if canonical_asin(term) else split_words(term)
        for root in roots:
            if not root:
                continue
            root_metrics[root] = root_metrics.get(root, Metrics()) + metrics
            root_terms.setdefault(root, OrderedDict())
            root_terms[root][term] = root_terms[root].get(term, Metrics()) + metrics
    return OrderedDict(
        (
            root,
            RootAggregate(root, metrics, tuple(terms.items())),
        )
        for root, metrics in root_metrics.items()
        for terms in [root_terms[root]]
    )
