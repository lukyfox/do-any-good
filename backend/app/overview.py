"""Progress overview ('development summary') computed from stored Goodies."""
from __future__ import annotations

from .storage import FileStorage, GoodyCategory


def build_overview(storage: FileStorage) -> dict:
    """Summarize the user's Goodies: planned vs. done/missed, counts, self/others."""
    goodies = storage.list_goodies()
    buckets: dict[str, list[dict]] = {"planned": [], "done": [], "missed": []}
    self_count = 0
    for goody in goodies:
        buckets[goody.status.value].append(goody.model_dump(mode="json"))
        if goody.category == GoodyCategory.SELF:
            self_count += 1
    return {
        "counts": {
            "total": len(goodies),
            "planned": len(buckets["planned"]),
            "done": len(buckets["done"]),
            "missed": len(buckets["missed"]),
            "self": self_count,
            "others": len(goodies) - self_count,
        },
        **buckets,
    }
