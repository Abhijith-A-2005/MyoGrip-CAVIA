"""Read-only view of one user's selection history for the dashboard History page.

Opens its own read-only SQLite connection per request, so it never touches the runtime thread's store.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def read_history(db: str | Path, user: str) -> dict[str, Any]:
    """Selections newest first, each joined with the menu it was confirmed from."""
    result: dict[str, Any] = {"user": user, "selections": [], "preferences": [], "summary": summary([])}
    if not Path(db).is_file():
        return result
    connection = sqlite3.connect(f"{Path(db).resolve().as_uri()}?mode=ro", uri=True, timeout=5.0)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT s.*, m.snapshot
            FROM selections s JOIN menus m ON m.id = s.menu_id
            WHERE s.user = ?
            ORDER BY s.created_at DESC, s.interaction_id DESC
            """,
            (user,),
        ).fetchall()
    except sqlite3.OperationalError:
        return result               # a database from before the arbitration tables existed
    finally:
        connection.close()

    selections = [selection(row) for row in rows]
    result["selections"] = selections
    result["preferences"] = preferences(rows)
    result["summary"] = summary(selections)
    return result


def selection(row: sqlite3.Row) -> dict[str, Any]:
    menu = json.loads(row["snapshot"])
    items = menu.get("items") or []
    from_full = bool(row["from_full_menu"])
    rank = items.index(row["grip"]) + 1 if not from_full and row["grip"] in items else None
    return {
        "id": row["interaction_id"],
        "time": row["created_at"],
        "object": row["object"],
        "region": row["region"],
        "grip": row["grip"],
        "menu": "full" if from_full else "adaptive",
        "rank": rank,
        "policy": menu.get("policy"),
        "items": items,
        "ranking_source": menu.get("ranking_source"),
        "region_confidence": (menu.get("context") or {}).get("region_confidence"),
        "compatible": bool(row["compatible"]),
        "instructed": bool(row["instructed"]),
        "status": row["status"],
        "grasp_success": None if row["grasp_success"] is None else bool(row["grasp_success"]),
    }


def preferences(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    """Grip counts per object and region, by the same rule as PreferenceStore.counts."""
    counts: dict[tuple[str, str, str], int] = {}
    for row in rows:
        if row["status"] == "accepted" and row["compatible"] and not row["instructed"]:
            key = (row["object"], row["region"], row["grip"])
            counts[key] = counts.get(key, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (kv[0][0], kv[0][1], -kv[1], kv[0][2]))
    return [{"object": o, "region": r, "grip": g, "n": n} for (o, r, g), n in ordered]


def summary(selections: list[dict[str, Any]]) -> dict[str, int]:
    def count(test) -> int:
        return sum(1 for s in selections if test(s))

    return {
        "total": len(selections),
        "accepted": count(lambda s: s["status"] == "accepted"),
        "cancelled": count(lambda s: s["status"] == "cancelled"),
        "adaptive": count(lambda s: s["menu"] == "adaptive"),
        "full": count(lambda s: s["menu"] == "full"),
        "first_option": count(lambda s: s["rank"] == 1),
    }
