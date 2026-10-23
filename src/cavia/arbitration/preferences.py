"""Persistent menu snapshots and shared selection history.

Use a store from one runtime thread.
Each interaction ID identifies one confirmed selection.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import time
from typing import Any

from .contracts import user_key


class PreferenceStore:
    def __init__(
        self,
        path: str | Path = "data/arbitration/history.sqlite3",
    ):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(
                parents=True,
                exist_ok=True,
            )

        self.connection = sqlite3.connect(
            str(path),
            timeout=5.0,
        )

        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")

        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS menus (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot TEXT NOT NULL,
                created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS selections (
                interaction_id TEXT PRIMARY KEY,
                menu_id INTEGER NOT NULL REFERENCES menus(id),
                user TEXT NOT NULL,
                object TEXT NOT NULL,
                region TEXT NOT NULL,
                grip TEXT NOT NULL,
                from_full_menu INTEGER NOT NULL,
                compatible INTEGER NOT NULL,
                instructed INTEGER NOT NULL,
                status TEXT NOT NULL CHECK(
                    status IN (
                        'pending',
                        'accepted',
                        'cancelled',
                        'failed'
                    )
                ),
                grasp_success INTEGER,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS selection_context
                ON selections(user, object, region, status);

            CREATE TABLE IF NOT EXISTS users (
                user TEXT PRIMARY KEY,
                created_at REAL NOT NULL
            );
        """)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> PreferenceStore:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def save_menu(self, snapshot: dict[str, Any]) -> int:
        """Save the exact menu/context used for later confirmation."""

        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT INTO menus(snapshot, created_at)
                VALUES (?, ?)
                """,
                ("{}", time.time()),
            )

            menu_id = int(cursor.lastrowid)
            payload = {**snapshot, "menu_id": menu_id}

            self.connection.execute(
                "UPDATE menus SET snapshot = ? WHERE id = ?",
                (
                    json.dumps(payload, allow_nan=False),
                    menu_id,
                ),
            )

        return menu_id

    def get_menu(self, menu_id: int) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT snapshot FROM menus WHERE id = ?",
            (menu_id,),
        ).fetchone()

        if row is None:
            raise KeyError(f"Unknown menu_id {menu_id}")

        return json.loads(row["snapshot"])

    def record_confirmation(
        self,
        menu_id: int,
        grip: str,
        interaction_id: str,
        *,
        from_full_menu: bool = False,
        instructed: bool = False,
    ) -> dict[str, Any]:
        """Record a pending selection without counting it yet.

        The caller verifies that the FSM accepted this menu.
        Reuse interaction_id for retries of the same confirmation.
        """

        if (
            not isinstance(interaction_id, str)
            or not interaction_id.strip()
        ):
            raise ValueError(
                "interaction_id must be a non-empty string"
            )

        if (
            type(from_full_menu) is not bool
            or type(instructed) is not bool
        ):
            raise ValueError(
                "from_full_menu and instructed must be booleans"
            )

        if not isinstance(grip, str):
            raise ValueError("grip must be a grip name")

        grip = grip.strip().upper()
        menu = self.get_menu(menu_id)

        options = (
            menu["full_menu"]
            if from_full_menu
            else menu["items"]
        )

        if grip not in options:
            raise ValueError(
                f"{grip} was not selectable in the specified menu"
            )

        now = time.time()

        values = (
            interaction_id,
            menu_id,
            menu["user"],
            menu["context"]["object"],
            menu["context"]["region"],
            grip,
            int(from_full_menu),
            int(grip in menu["compatible"]),
            int(instructed),
            "pending",
            None,
            now,
            now,
        )

        with self.connection:
            self.connection.execute(
                """
                INSERT INTO selections
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(interaction_id) DO NOTHING
                """,
                values,
            )

            saved = self.get_selection(interaction_id)

            expected = (
                menu_id,
                grip,
                int(from_full_menu),
                int(instructed),
            )

            actual = tuple(
                saved[key]
                for key in (
                    "menu_id",
                    "grip",
                    "from_full_menu",
                    "instructed",
                )
            )

            if actual != expected:
                raise ValueError(
                    "interaction_id was already used "
                    "for different feedback"
                )

        return saved

    def finish(
        self,
        interaction_id: str,
        outcome: str,
        *,
        grasp_success: bool | None = None,
    ) -> dict[str, Any]:
        """Resolve pending feedback after the cancellation check.

        accepted means eligible preference, not physical success.
        A later cancellation/failure can invalidate an accepted choice.
        """

        if outcome not in {"accepted", "cancelled", "failed"}:
            raise ValueError(
                "outcome must be accepted, cancelled or failed"
            )

        if (
            grasp_success is not None
            and type(grasp_success) is not bool
        ):
            raise ValueError(
                "grasp_success must be bool or None"
            )

        if outcome == "accepted" and grasp_success is False:
            raise ValueError(
                "Use failed for an observed unsuccessful grasp"
            )

        if outcome != "accepted" and grasp_success is True:
            raise ValueError(
                "Successful grasp feedback conflicts with this outcome"
            )

        with self.connection:
            # Acquire the write lock before checking the old status.
            self.connection.execute(
                """
                UPDATE selections
                SET updated_at = updated_at
                WHERE interaction_id = ?
                """,
                (interaction_id,),
            )

            row = self.get_selection(interaction_id)

            if (
                row["status"] in {"cancelled", "failed"}
                and outcome != row["status"]
            ):
                raise ValueError(
                    "A cancelled/failed interaction is terminal"
                )

            observed = (
                row["grasp_success"]
                if grasp_success is None
                else int(grasp_success)
            )

            if outcome != "accepted":
                observed = 0 if outcome == "failed" else None

            self.connection.execute(
                """
                UPDATE selections
                SET status = ?, grasp_success = ?, updated_at = ?
                WHERE interaction_id = ?
                """,
                (
                    outcome,
                    observed,
                    time.time(),
                    interaction_id,
                ),
            )

        return self.get_selection(interaction_id)

    def get_selection(
        self,
        interaction_id: str,
    ) -> dict[str, Any]:
        row = self.connection.execute(
            """
            SELECT *
            FROM selections
            WHERE interaction_id = ?
            """,
            (interaction_id,),
        ).fetchone()

        if row is None:
            raise KeyError(
                f"Unknown interaction_id {interaction_id}"
            )

        return dict(row)

    def counts(
        self,
        user: str | int,
        object_name: str,
        region: str | None = None,
    ) -> dict[str, int]:
        """region=None aggregates all regions exactly once."""

        query = """
            SELECT grip, COUNT(*) AS n
            FROM selections
            WHERE user = ?
              AND object = ?
              AND status = 'accepted'
              AND compatible = 1
              AND instructed = 0
        """

        params: list[Any] = [
            user_key(user),
            object_name,
        ]

        if region is not None:
            query += " AND region = ?"
            params.append(region)

        query += " GROUP BY grip"

        return {
            row["grip"]: row["n"]
            for row in self.connection.execute(query, params)
        }

    def history(
        self,
        user: str | int | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM selections"
        params: tuple[str, ...] = ()

        if user is not None:
            query += " WHERE user = ?"
            params = (user_key(user),)

        query += " ORDER BY created_at, interaction_id"

        return [
            dict(row)
            for row in self.connection.execute(query, params)
        ]

    def add_user(self, user: str | int) -> str:
        """Register a profile before it has any history. Idempotent."""

        key = user_key(user)

        with self.connection:
            self.connection.execute(
                """
                INSERT OR IGNORE INTO users(user, created_at)
                VALUES (?, ?)
                """,
                (key, time.time()),
            )

        return key

    def users(self) -> list[dict[str, Any]]:
        """Registered users plus any user found in the history, oldest first."""

        rows = self.connection.execute(
            """
            WITH known AS (
                SELECT user, created_at FROM users
                UNION ALL
                SELECT user, MIN(created_at) FROM selections GROUP BY user
            )
            SELECT
                known.user AS user,
                MIN(known.created_at) AS created_at,
                (
                    SELECT COUNT(*) FROM selections s
                    WHERE s.user = known.user
                ) AS selections,
                (
                    SELECT COUNT(*) FROM selections s
                    WHERE s.user = known.user AND s.status = 'accepted'
                ) AS accepted,
                (
                    SELECT MAX(updated_at) FROM selections s
                    WHERE s.user = known.user
                ) AS last_used
            FROM known
            GROUP BY known.user
            ORDER BY MIN(known.created_at), known.user
            """
        )

        return [dict(row) for row in rows]
