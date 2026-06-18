"""
Telemetry module backed by SQLAlchemy so production can use Postgres while
local development can still default to SQLite.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, case, create_engine, func
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy import text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from src.backend.settings import get_settings


class Base(DeclarativeBase):
    """Base declarative metadata for telemetry models."""


class QueryLog(Base):
    __tablename__ = "queries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str | None] = mapped_column(String(64), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    query: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    tools_called: Mapped[list[str]] = mapped_column(JSON)
    tool_results_summary: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    tool_timings_ms: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    total_tool_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[float] = mapped_column(Float)
    latency_ms: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default="success", index=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retryable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    client_ip: Mapped[str | None] = mapped_column(String(128), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)


class TelemetryEvent(Base):
    __tablename__ = "telemetry_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str | None] = mapped_column(String(64), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    level: Mapped[str] = mapped_column(String(16), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    message: Mapped[str] = mapped_column(Text)
    context: Mapped[dict[str, Any]] = mapped_column(JSON)


QUERY_MIGRATION_COLUMNS = {
    "tool_results_summary": "JSON",
    "tool_timings_ms": "JSON",
    "total_tool_latency_ms": "FLOAT DEFAULT 0.0",
    "client_ip": "VARCHAR(128)",
    "user_id": "VARCHAR(128)",
}


def utcnow() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


@lru_cache(maxsize=1)
def get_engine():
    """Create and cache the SQLAlchemy engine for the configured database."""
    settings = get_settings()
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    return create_engine(
        settings.database_url,
        future=True,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


@lru_cache(maxsize=1)
def get_session_factory():
    """Create and cache a session factory."""
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


def init_db() -> None:
    """Create tables if they do not already exist."""
    engine = get_engine()
    Base.metadata.create_all(engine)

    inspector = sqlalchemy_inspect(engine)
    table_names = inspector.get_table_names()
    if "queries" in table_names:
        existing_columns = {
            column["name"]
            for column in inspector.get_columns("queries")
        }
        missing_columns = {
            name: ddl
            for name, ddl in QUERY_MIGRATION_COLUMNS.items()
            if name not in existing_columns
        }
        if missing_columns:
            with engine.begin() as connection:
                for column_name, ddl in missing_columns.items():
                    connection.execute(
                        text(f"ALTER TABLE queries ADD COLUMN {column_name} {ddl}")
                    )


def log_query(
    query: str,
    result: dict,
    *,
    request_id: str | None = None,
    status: str = "success",
    error_code: str | None = None,
    error_message: str | None = None,
    retryable: bool | None = None,
    client_ip: str | None = None,
    user_id: str | None = None,
) -> None:
    """Insert one telemetry row from the result dict returned by run_fda_query."""
    init_db()
    with get_session_factory()() as session:
        session.add(
            QueryLog(
                request_id=request_id,
                timestamp=utcnow(),
                query=query,
                answer=result.get("answer", ""),
                tools_called=result.get("tools_called", []),
                tool_results_summary=_build_tool_results_summary(result.get("tool_results", [])),
                tool_timings_ms=_build_tool_timings(result.get("tool_results", [])),
                total_tool_latency_ms=_sum_tool_latency(result.get("tool_results", [])),
                input_tokens=result.get("input_tokens", 0),
                output_tokens=result.get("output_tokens", 0),
                cost_usd=result.get("cost_usd", 0.0),
                latency_ms=result.get("latency_ms", 0.0),
                status=status,
                error_code=error_code,
                error_message=error_message,
                retryable=retryable,
                client_ip=client_ip,
                user_id=user_id,
            )
        )
        session.commit()


def log_event(
    *,
    level: str,
    event_type: str,
    message: str,
    request_id: str | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    """Persist an operational event for later inspection."""
    init_db()
    with get_session_factory()() as session:
        session.add(
            TelemetryEvent(
                request_id=request_id,
                timestamp=utcnow(),
                level=level.upper(),
                event_type=event_type,
                message=message,
                context=context or {},
            )
        )
        session.commit()


def get_all_queries() -> list[dict]:
    """Return all logged queries as a list of dicts, newest first."""
    init_db()
    with get_session_factory()() as session:
        rows = session.query(QueryLog).order_by(QueryLog.id.desc()).all()
        return [_query_to_dict(row) for row in rows]


def get_recent_events(limit: int = 100) -> list[dict]:
    """Return recent telemetry events, newest first."""
    init_db()
    with get_session_factory()() as session:
        rows = (
            session.query(TelemetryEvent)
            .order_by(TelemetryEvent.id.desc())
            .limit(limit)
            .all()
        )
        return [_event_to_dict(row) for row in rows]


def get_metrics() -> dict:
    """Return aggregate statistics across all logged queries and events."""
    init_db()
    with get_session_factory()() as session:
        query_metrics = session.query(
            func.count(QueryLog.id),
            func.coalesce(
                func.sum(case((QueryLog.status == "success", 1), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(case((QueryLog.status != "success", 1), else_=0)),
                0,
            ),
            func.coalesce(func.sum(QueryLog.cost_usd), 0.0),
            func.coalesce(func.avg(QueryLog.latency_ms), 0.0),
            func.coalesce(func.avg(QueryLog.input_tokens + QueryLog.output_tokens), 0.0),
            func.coalesce(func.avg(QueryLog.total_tool_latency_ms), 0.0),
        ).one()
        total_error_events = (
            session.query(func.count(TelemetryEvent.id))
            .filter(TelemetryEvent.level.in_(["ERROR", "WARNING"]))
            .scalar()
        )

    return {
        "total_queries": int(query_metrics[0] or 0),
        "successful_queries": int(query_metrics[1] or 0),
        "failed_queries": int(query_metrics[2] or 0),
        "total_cost_usd": float(query_metrics[3] or 0.0),
        "avg_latency_ms": float(query_metrics[4] or 0.0),
        "avg_tokens": float(query_metrics[5] or 0.0),
        "avg_tool_latency_ms": float(query_metrics[6] or 0.0),
        "total_error_events": int(total_error_events or 0),
    }


def _build_tool_results_summary(tool_results: list[dict]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for tool_call in tool_results:
        tool_output = tool_call.get("tool_output", {})
        summary.append(
            {
                "tool_name": tool_call.get("tool_name"),
                "query": tool_output.get("query"),
                "result_count": tool_output.get("result_count", 0),
                "duration_ms": tool_call.get("duration_ms", 0.0),
            }
        )
    return summary


def _build_tool_timings(tool_results: list[dict]) -> list[dict[str, Any]]:
    return [
        {
            "tool_name": tool_call.get("tool_name"),
            "duration_ms": tool_call.get("duration_ms", 0.0),
        }
        for tool_call in tool_results
    ]


def _sum_tool_latency(tool_results: list[dict]) -> float:
    return round(
        sum(float(tool_call.get("duration_ms", 0.0) or 0.0) for tool_call in tool_results),
        1,
    )


def _query_to_dict(row: QueryLog) -> dict:
    return {
        "id": row.id,
        "request_id": row.request_id,
        "timestamp": row.timestamp.isoformat(),
        "query": row.query,
        "answer": row.answer,
        "tools_called": row.tools_called or [],
        "tool_results_summary": row.tool_results_summary or [],
        "tool_timings_ms": row.tool_timings_ms or [],
        "total_tool_latency_ms": row.total_tool_latency_ms or 0.0,
        "input_tokens": row.input_tokens,
        "output_tokens": row.output_tokens,
        "cost_usd": row.cost_usd,
        "latency_ms": row.latency_ms,
        "status": row.status,
        "error_code": row.error_code,
        "error_message": row.error_message,
        "retryable": row.retryable,
        "client_ip": row.client_ip,
        "user_id": row.user_id,
    }


def _event_to_dict(row: TelemetryEvent) -> dict:
    return {
        "id": row.id,
        "request_id": row.request_id,
        "timestamp": row.timestamp.isoformat(),
        "level": row.level,
        "event_type": row.event_type,
        "message": row.message,
        "context": row.context or {},
    }
