from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


class BudgetLimitExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class BudgetSnapshot:
    date: str
    api_calls: int
    cost_usd: float


class BudgetTracker:
    def __init__(self, db_path: Path, max_daily_api_calls: int, max_daily_cost_usd: float):
        self.db_path = db_path
        self.max_daily_api_calls = max(0, int(max_daily_api_calls))
        self.max_daily_cost_usd = max(0.0, float(max_daily_cost_usd))
        self._init_db()

    @property
    def enabled(self) -> bool:
        return self.max_daily_api_calls > 0 or self.max_daily_cost_usd > 0

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS budget_log (
                    date TEXT NOT NULL,
                    worker TEXT NOT NULL,
                    api_calls INTEGER NOT NULL DEFAULT 0,
                    cost_usd REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY (date, worker)
                )
                """
            )
            conn.commit()

    def _utc_date(self) -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def _today_snapshot(self) -> BudgetSnapshot:
        date_value = self._utc_date()
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(api_calls), 0), COALESCE(SUM(cost_usd), 0) FROM budget_log WHERE date = ?",
                (date_value,),
            ).fetchone()
        api_calls = int(row[0] if row else 0)
        cost_usd = float(row[1] if row else 0.0)
        return BudgetSnapshot(date=date_value, api_calls=api_calls, cost_usd=cost_usd)

    def check_budget(self) -> BudgetSnapshot:
        snapshot = self._today_snapshot()
        violations: list[str] = []

        if self.max_daily_api_calls > 0 and snapshot.api_calls >= self.max_daily_api_calls:
            violations.append(
                f"MAX_DAILY_API_CALLS reached: used={snapshot.api_calls}, limit={self.max_daily_api_calls}"
            )
        if self.max_daily_cost_usd > 0 and snapshot.cost_usd >= self.max_daily_cost_usd:
            violations.append(
                f"MAX_DAILY_COST_USD reached: used={snapshot.cost_usd:.6f}, limit={self.max_daily_cost_usd:.6f}"
            )

        if violations:
            raise BudgetLimitExceeded("; ".join(violations))

        return snapshot

    def log_budget(self, worker: str, *, api_calls: int = 1, cost_usd: float = 0.0) -> None:
        if api_calls < 0:
            api_calls = 0
        if cost_usd < 0:
            cost_usd = 0.0

        date_value = self._utc_date()
        worker_value = worker.strip() or "unknown"

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO budget_log (date, worker, api_calls, cost_usd)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(date, worker) DO UPDATE SET
                    api_calls = api_calls + excluded.api_calls,
                    cost_usd = cost_usd + excluded.cost_usd
                """,
                (date_value, worker_value, int(api_calls), float(cost_usd)),
            )
            conn.commit()
