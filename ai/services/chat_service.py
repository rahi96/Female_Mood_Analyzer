import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnableLambda

from ai.config import settings
from ai.models.chat_models import (
    ChatDataSummary,
    ChatHistoryRequest,
    ChatHistoryResponse,
    ChatLimitReachedDetail,
    ChatMessage,
    ChatPlan,
    ChatResponse,
    ChatResponseRequest,
    ConversationRecord,
    TemperatureStats,
)
from ai.services.cycle_service import fetch_backend_data, fetch_subscription
from ai.utils.llm_call import llm_call


class ChatLimitReached(Exception):
    def __init__(self, detail: ChatLimitReachedDetail):
        self.detail = detail
        super().__init__(detail.message)


CHATBOT_SYSTEM_PROMPT = """
You are a Health Data Analysis Assistant, designed to help users understand their health metrics and temperature logs. You have access to the user's complete onboarding and temperature tracking data.

## Your Role
- Analyze the user's health data comprehensively before responding
- Provide personalized insights based on their specific data patterns
- Maintain conversation context across multiple interactions
- Be empathetic, clear, and professional in all responses

## Data Context
You have access to the user's complete health profile through the user_data variable, which includes:
- Temperature logs and patterns
- Onboarding information
- Historical health metrics
- Any relevant medical tracking data

CRITICAL: Always reference the actual data provided. Never make assumptions about data you haven't seen.

## Response Guidelines

### Data Analysis Process
1. First, examine the data structure: Understand what fields are available
2. Identify patterns: Look for trends, anomalies, or significant changes
3. Context consideration: Review conversation history to maintain continuity
4. Formulate response: Provide specific, data-driven insights

### Response Style
- Use clear, non-technical language unless the user prefers medical terminology
- Always cite specific data points when making observations, for example "Your temperature on [date] was [value]"
- Break down complex patterns into understandable insights
- Ask clarifying questions when the user's intent is unclear
- Keep responses concise by default: 2-5 short paragraphs unless the user asks for a detailed breakdown
- Do not use emojis

### Safety and Limitations
IMPORTANT MEDICAL DISCLAIMER:
- You are NOT a replacement for professional medical advice
- Always encourage users to consult healthcare providers for medical concerns
- If you detect potentially concerning patterns, such as persistent fever or unusual trends, recommend medical consultation
- Never diagnose conditions or prescribe treatments
- Frame insights as observations, not medical conclusions

### Handling Missing Data
- If specific data is unavailable, clearly state this
- Suggest what information would be helpful to provide better insights
- Do not fabricate or assume data values

## Response Format

Structure your responses as follows:

1. Acknowledgment: Briefly acknowledge the user's question
2. Data Summary: Highlight relevant data points from their records
3. Analysis: Provide insights based on the data
4. Actionable Advice: Offer practical suggestions if appropriate
5. Follow-up: Invite further questions or clarification

## Context Maintenance
- Reference previous questions and answers when relevant
- Build upon earlier insights in the conversation
- If the user asks about something discussed before, acknowledge continuity
- Summarize key points from the conversation when helpful

## Technical Instructions
- Always validate that user_data is available before analysis
- Handle missing or incomplete data gracefully
- Maintain HIPAA-like privacy consciousness and never share data externally
- Structure responses for easy parsing if needed for UI display

Remember: Your goal is to help users understand their health data, not to replace medical professionals. Be informative, supportive, and always prioritize user safety.
"""


MAX_HISTORY_MESSAGES = 10
MEMORY_SUMMARY_BATCH_SIZE = 8
RETRYABLE_LLM_STATUS_CODES = {429, 500, 502, 503, 529}
LLM_RETRY_DELAYS_SECONDS = (1.0, 2.0)


CHAT_MESSAGE_TEMPLATE = """
## Current User Data
```json
{user_data}
```

## Long-Term User Memory
{long_term_memory}

## Recent Conversation History
{conversation_history}

## Current User Question
{user_question}

---

Based on the user data, long-term memory, and recent conversation context, provide a helpful, personalized response. Remember to:
1. Analyze the actual data before responding
2. Use long-term memory only when it is relevant to this question
3. Maintain continuity from recent messages
4. Be specific and cite data points
5. Include appropriate medical disclaimers when relevant
6. Ask clarifying questions if needed
"""


MEMORY_SUMMARY_TEMPLATE = """
You maintain long-term memory for a health-data chatbot.

Current memory summary:
{current_summary}

New conversation messages:
{new_messages}

Update the memory summary so future responses can stay context-aware over long conversations.

Keep only durable, useful information:
- The user's recurring health-data interests, goals, or concerns
- Important temperature or cycle observations already discussed
- User preferences about explanation style
- Open questions or follow-up topics

Rules:
- Do not diagnose or claim medical certainty
- Do not invent facts
- Keep it concise, factual, and useful
- Return only the updated memory summary
"""


CHAT_PROMPT = PromptTemplate.from_template(CHAT_MESSAGE_TEMPLATE)
MEMORY_SUMMARY_PROMPT = PromptTemplate.from_template(MEMORY_SUMMARY_TEMPLATE)


def generate_chat_response(request: ChatResponseRequest) -> ChatResponse:
    session_id = request.session_id or str(uuid4())
    timestamp = _utc_timestamp()

    _enforce_chat_quota(request.user_id)

    user_data = fetch_backend_data(request.user_id)
    history = _get_history(request.user_id, session_id)
    long_term_memory = _get_long_term_memory(request.user_id)

    response_text = _run_chat_chain(
        user_data=user_data,
        conversation_history=[record.model_dump() for record in history],
        long_term_memory=long_term_memory,
        user_question=request.message,
    )
    response_text = _clean_response(response_text) or _fallback_response(user_data)

    _append_history(
        request.user_id,
        session_id,
        ConversationRecord(role="user", content=request.message, timestamp=timestamp),
    )
    _append_history(
        request.user_id,
        session_id,
        ConversationRecord(role="assistant", content=response_text, timestamp=_utc_timestamp()),
    )
    _increment_chats_used(request.user_id)
    _maybe_update_long_term_memory(request.user_id)

    stats = _extract_temperature_stats(user_data)

    return ChatResponse(
        response=response_text,
        session_id=session_id,
        timestamp=timestamp,
        data_summary=ChatDataSummary(
            temperature_range=stats.temperature_range,
            data_points_analyzed=stats.data_points_analyzed,
        ),
    )


def get_chat_history(request: ChatHistoryRequest) -> ChatHistoryResponse:
    if request.session_id:
        history = _get_history(request.user_id, request.session_id)
        return _history_response(history, request.session_id)

    all_history = _get_user_history(request.user_id)
    return _history_response(all_history, None)


def _enforce_chat_quota(user_id: str) -> None:
    plan = fetch_user_plan(user_id)
    chats_used = _get_chats_used(user_id)
    chat_limit = _chat_limit_for_plan(plan)

    if chat_limit is None or chats_used < chat_limit:
        return

    upgrade_to: Literal["premium", "elite"] = "elite" if plan == "premium" else "premium"
    raise ChatLimitReached(
        ChatLimitReachedDetail(
            plan=plan,
            chat_limit=chat_limit,
            chats_used=chats_used,
            chats_remaining=0,
            upgrade_to=upgrade_to,
            message=(
                "Free chat limit reached. Purchase Premium to continue."
                if plan == "free"
                else "Chat limit reached. Upgrade your plan to continue."
            ),
        )
    )


def fetch_user_plan(user_id: str) -> ChatPlan:
    """Read plan from healthcare backend. Defaults to free if unavailable."""
    try:
        payload = fetch_subscription(user_id)
    except Exception:
        return "free"

    raw = payload.get("plan") or payload.get("subscription") or payload.get("tier")
    if isinstance(raw, dict):
        raw = raw.get("plan") or raw.get("name") or raw.get("type")

    plan = str(raw or "free").strip().lower()
    if plan in {"free", "premium", "elite"}:
        return plan  # type: ignore[return-value]
    return "free"


def _chat_limit_for_plan(plan: ChatPlan) -> int | None:
    if plan == "free":
        return settings.FREE_CHAT_LIMIT
    if plan == "premium":
        return settings.PREMIUM_CHAT_LIMIT
    return None


def _get_chats_used(user_id: str) -> int:
    with _connect_chat_db() as conn:
        row = conn.execute(
            "SELECT chats_used FROM chat_usage WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return int(row["chats_used"]) if row else 0


def _increment_chats_used(user_id: str) -> None:
    with _connect_chat_db() as conn:
        conn.execute(
            """
            INSERT INTO chat_usage (user_id, chats_used, updated_at)
            VALUES (?, 1, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                chats_used = chats_used + 1,
                updated_at = excluded.updated_at
            """,
            (user_id, _utc_timestamp()),
        )
        conn.commit()


def construct_message_prompt(
    user_data: dict,
    conversation_history: list,
    user_question: str,
    long_term_memory: str | None = None,
) -> str:
    return CHAT_PROMPT.format(
        user_data=json.dumps(user_data, indent=2, ensure_ascii=True, default=str),
        long_term_memory=long_term_memory or "No long-term memory stored yet.",
        conversation_history=format_conversation_history(conversation_history),
        user_question=user_question,
    )


def format_conversation_history(history: list) -> str:
    if not history:
        return "This is the start of the conversation."

    formatted = []
    for msg in history[-MAX_HISTORY_MESSAGES:]:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        formatted.append(f"**{str(role).upper()}**: {content}")

    return "\n\n".join(formatted)


def _run_chat_chain(
    user_data: dict,
    conversation_history: list,
    long_term_memory: str,
    user_question: str,
) -> str:
    chain = (
        CHAT_PROMPT
        | RunnableLambda(lambda prompt_value: _call_chat_llm(_prompt_to_string(prompt_value)))
        | RunnableLambda(_clean_response)
    )

    return chain.invoke(
        {
            "user_data": json.dumps(user_data, indent=2, ensure_ascii=True, default=str),
            "long_term_memory": long_term_memory or "No long-term memory stored yet.",
            "conversation_history": format_conversation_history(conversation_history),
            "user_question": user_question,
        }
    )


def _call_chat_llm(prompt: str) -> str:
    attempts = len(LLM_RETRY_DELAYS_SECONDS) + 1

    for attempt in range(attempts):
        try:
            return llm_call(
                prompt=prompt,
                system=CHATBOT_SYSTEM_PROMPT,
                max_tokens=900,
            )
        except Exception as exc:
            is_last_attempt = attempt == attempts - 1
            if not _is_retryable_llm_error(exc):
                raise
            if is_last_attempt:
                return ""
            time.sleep(LLM_RETRY_DELAYS_SECONDS[attempt])

    return ""


def _run_memory_summary_chain(current_summary: str, new_messages: str) -> str:
    chain = (
        MEMORY_SUMMARY_PROMPT
        | RunnableLambda(lambda prompt_value: _call_memory_llm(_prompt_to_string(prompt_value)))
        | RunnableLambda(_clean_response)
    )

    return chain.invoke(
        {
            "current_summary": current_summary or "No long-term memory stored yet.",
            "new_messages": new_messages,
        }
    )


def _call_memory_llm(prompt: str) -> str:
    attempts = len(LLM_RETRY_DELAYS_SECONDS) + 1

    for attempt in range(attempts):
        try:
            return llm_call(
                prompt=prompt,
                system=CHATBOT_SYSTEM_PROMPT,
                max_tokens=650,
            )
        except Exception as exc:
            is_last_attempt = attempt == attempts - 1
            if not _is_retryable_llm_error(exc):
                raise
            if is_last_attempt:
                return ""
            time.sleep(LLM_RETRY_DELAYS_SECONDS[attempt])

    return ""


def _prompt_to_string(prompt_value: Any) -> str:
    if hasattr(prompt_value, "to_string"):
        return prompt_value.to_string()
    return str(prompt_value)


def _is_retryable_llm_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code in RETRYABLE_LLM_STATUS_CODES:
        return True

    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "overloaded",
            "rate_limit",
            "rate limit",
            "temporarily unavailable",
            "timeout",
        )
    )


def _fallback_response(user_data: dict) -> str:
    stats = _extract_temperature_stats(user_data)
    if stats.data_points_analyzed:
        return (
            f"I found {stats.data_points_analyzed} temperature readings in your data, "
            f"with a range of {stats.temperature_range}. Keep logging consistently, "
            "and consult a healthcare professional if you notice persistent fever or unusual symptoms."
        )

    return (
        "I could not find temperature readings in your current data. Please keep logging your readings, "
        "and consult a healthcare professional if you have symptoms or health concerns."
    )


def _get_history(user_id: str, session_id: str) -> list[ConversationRecord]:
    with _connect_chat_db() as conn:
        rows = conn.execute(
            """
            SELECT role, content, timestamp
            FROM chat_messages
            WHERE user_id = ? AND session_id = ?
            ORDER BY id ASC
            """,
            (user_id, session_id),
        ).fetchall()

    return [_record_from_row(row) for row in rows]


def _get_user_history(user_id: str) -> list[ConversationRecord]:
    with _connect_chat_db() as conn:
        rows = conn.execute(
            """
            SELECT role, content, timestamp
            FROM chat_messages
            WHERE user_id = ?
            ORDER BY id ASC
            """,
            (user_id,),
        ).fetchall()

    return [_record_from_row(row) for row in rows]


def _get_long_term_memory(user_id: str) -> str:
    with _connect_chat_db() as conn:
        row = conn.execute(
            """
            SELECT summary
            FROM chat_memories
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()

    if not row or not row["summary"]:
        return ""
    return row["summary"]


def _maybe_update_long_term_memory(user_id: str) -> None:
    with _connect_chat_db() as conn:
        row = conn.execute(
            """
            SELECT summary, summarized_message_count
            FROM chat_memories
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
        total_messages = conn.execute(
            """
            SELECT COUNT(*)
            FROM chat_messages
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()[0]

        current_summary = row["summary"] if row else ""
        summarized_count = row["summarized_message_count"] if row else 0

    unsummarized_count = total_messages - summarized_count
    should_create_first_summary = not current_summary and total_messages > MAX_HISTORY_MESSAGES
    should_refresh_summary = bool(current_summary) and unsummarized_count >= MEMORY_SUMMARY_BATCH_SIZE

    if not should_create_first_summary and not should_refresh_summary:
        return

    new_messages = _get_user_history_after_offset(user_id, summarized_count)
    formatted_messages = _format_memory_messages(new_messages)
    if not formatted_messages:
        return

    try:
        updated_summary = _run_memory_summary_chain(current_summary, formatted_messages)
    except Exception:
        return

    if not updated_summary:
        return

    _upsert_long_term_memory(user_id, updated_summary, total_messages)


def _get_user_history_after_offset(
    user_id: str,
    offset: int,
) -> list[ConversationRecord]:
    with _connect_chat_db() as conn:
        rows = conn.execute(
            """
            SELECT role, content, timestamp
            FROM chat_messages
            WHERE user_id = ?
            ORDER BY id ASC
            LIMIT -1 OFFSET ?
            """,
            (user_id, offset),
        ).fetchall()

    return [_record_from_row(row) for row in rows]


def _format_memory_messages(history: list[ConversationRecord]) -> str:
    if not history:
        return ""

    return "\n\n".join(
        f"{record.timestamp} {record.role.upper()}: {record.content}"
        for record in history
    )


def _upsert_long_term_memory(
    user_id: str,
    summary: str,
    summarized_message_count: int,
) -> None:
    with _connect_chat_db() as conn:
        conn.execute(
            """
            INSERT INTO chat_memories (
                user_id,
                summary,
                summarized_message_count,
                updated_at
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                summary = excluded.summary,
                summarized_message_count = excluded.summarized_message_count,
                updated_at = excluded.updated_at
            """,
            (user_id, summary, summarized_message_count, _utc_timestamp()),
        )
        conn.commit()


def _append_history(user_id: str, session_id: str, record: ConversationRecord) -> None:
    with _connect_chat_db() as conn:
        conn.execute(
            """
            INSERT INTO chat_messages (user_id, session_id, role, content, timestamp)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, session_id, record.role, record.content, record.timestamp),
        )
        conn.commit()


def _connect_chat_db() -> sqlite3.Connection:
    db_path = _chat_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    _ensure_chat_schema(conn)
    return conn


def _chat_db_path() -> Path:
    db_path = Path(settings.CHAT_HISTORY_DB_PATH)
    if db_path.is_absolute():
        return db_path
    return Path.cwd() / db_path


def _ensure_chat_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
            content TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_messages_user_session
        ON chat_messages (user_id, session_id, id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_messages_user
        ON chat_messages (user_id, id)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_memories (
            user_id TEXT PRIMARY KEY,
            summary TEXT NOT NULL DEFAULT '',
            summarized_message_count INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_usage (
            user_id TEXT PRIMARY KEY,
            chats_used INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _record_from_row(row: sqlite3.Row) -> ConversationRecord:
    return ConversationRecord(
        role=row["role"],
        content=row["content"],
        timestamp=row["timestamp"],
    )


def _history_response(
    history: list[ConversationRecord],
    session_id: str | None,
) -> ChatHistoryResponse:
    messages = [
        ChatMessage(role=record.role, content=record.content, timestamp=record.timestamp)
        for record in history
    ]
    return ChatHistoryResponse(
        history=messages,
        total_messages=len(messages),
        session_id=session_id,
    )


def _extract_temperature_stats(user_data: dict) -> TemperatureStats:
    points = _collect_temperature_points(user_data)
    values = [point["value"] for point in points]
    dates = [point["date"] for point in points if point.get("date")]

    if not values:
        return TemperatureStats(
            temperature_range="No temperature logs found",
            data_points_analyzed=0,
            raw=user_data,
        )

    minimum = min(values)
    maximum = max(values)

    return TemperatureStats(
        temperature_range=f"{minimum:g} - {maximum:g}",
        data_points_analyzed=len(values),
        values=values,
        dates=dates,
        raw=user_data,
    )


def _collect_temperature_points(data: Any) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            temp = _temperature_from_mapping(value)
            if temp is not None:
                points.append(
                    {
                        "value": temp,
                        "date": _date_from_mapping(value),
                    }
                )

            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(data)
    return points


def _temperature_from_mapping(value: dict) -> float | None:
    for key, raw in value.items():
        normalized = _normalize_key(key)
        if normalized in {"temp", "temperature", "bbt", "basalbodytemperature"}:
            return _to_float(raw)
    return None


def _date_from_mapping(value: dict) -> str | None:
    for key in ("date", "logDate", "loggedAt", "createdAt", "created_at", "time"):
        raw = value.get(key)
        if raw:
            return str(raw)
    return None


def _normalize_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value)
        if match:
            return float(match.group(0))
    return None


def _clean_response(text: str) -> str:
    return " ".join(text.strip().split())


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
