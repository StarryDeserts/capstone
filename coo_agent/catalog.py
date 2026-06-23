from __future__ import annotations

from dataclasses import dataclass, field

import yaml

REQUIRED_ROLES = ("research", "verify", "format")


@dataclass
class CatalogEntry:
    role: str
    service_id: str
    price_usdc: float
    tags: list[str] = field(default_factory=list)
    external: bool = False


class Catalog:
    def __init__(self, entries: dict[str, list[CatalogEntry]]):
        self._entries = entries
        self._rr: dict[str, int] = {role: 0 for role in entries}

    @classmethod
    def load(cls, path: str) -> "Catalog":
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        entries: dict[str, list[CatalogEntry]] = {}
        for role, items in raw.items():
            parsed = []
            for it in items or []:
                price = float(it["price_usdc"])
                if price < 0:
                    raise ValueError(f"negative price for {it.get('service_id')}")
                parsed.append(CatalogEntry(role=role, service_id=it["service_id"],
                    price_usdc=price, tags=list(it.get("tags", [])),
                    external=bool(it.get("external", False))))
            # own entries first, external last (stable selection preference)
            parsed.sort(key=lambda e: e.external)
            entries[role] = parsed
        for role in REQUIRED_ROLES:
            if not entries.get(role):
                raise ValueError(f"catalog missing required role: {role}")
        return cls(entries)

    def candidates(self, role: str, exclude: set[str] = frozenset()) -> list[CatalogEntry]:
        return [e for e in self._entries.get(role, []) if e.service_id not in exclude]

    def select(self, role: str, exclude: set[str] = frozenset(),
               policy: str = "round_robin") -> "CatalogEntry | None":
        cands = self.candidates(role, exclude)
        if not cands:
            return None
        if policy == "cheapest":
            return min(cands, key=lambda e: e.price_usdc)
        idx = self._rr.get(role, 0) % len(cands)
        self._rr[role] = idx + 1
        return cands[idx]
