import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from openai import OpenAI

logger = logging.getLogger(__name__)

VALID_UNITS = {"days", "weeks", "months"}
DEFAULT_INTERVAL = {"value": 30, "unit": "days"}
MAX_RETRIES = 3

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


@dataclass
class ScheduleResult:
    value: int
    unit: str
    next_check_at: datetime


def schedule_next_check(prediction_text: str, investigation_summary: str) -> ScheduleResult:
    """Decide when to next re-investigate an unresolved prediction. Always returns a result."""
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            raw = _call_llm(prediction_text, investigation_summary)
            return _parse_and_validate(raw)
        except Exception as exc:
            last_error = exc
            wait = 2 ** attempt
            logger.warning("Scheduler attempt %d/%d failed: %s — retrying in %ds", attempt + 1, MAX_RETRIES, exc, wait)
            time.sleep(wait)

    logger.warning("Scheduler failed after %d attempts — using default 30 days. Error: %s", MAX_RETRIES, last_error)
    return _build_result(DEFAULT_INTERVAL)


def _call_llm(prediction_text: str, investigation_summary: str) -> str:
    system = (
        "You decide when to re-investigate unresolved predictions. "
        "Return JSON with exactly two fields:\n"
        '- "value": integer between 1 and 365\n'
        '- "unit": one of "days", "weeks", "months"\n\n'
        "Consider when the predicted event is supposed to occur and "
        "how much time needs to pass before new evidence is likely. "
        "Only return JSON."
    )
    user = (
        f"PREDICTION: {prediction_text}\n\n"
        f"LATEST INVESTIGATION: {investigation_summary}\n\n"
        "When should we check again?"
    )
    response = _get_client().chat.completions.create(
        model="gpt-4.1",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return response.choices[0].message.content


def _parse_and_validate(raw: str) -> ScheduleResult:
    try:
        data = json.loads(raw)
        value = int(data.get("value", 0))
        unit = str(data.get("unit", ""))
    except (json.JSONDecodeError, ValueError, TypeError):
        logger.warning("Scheduler returned malformed JSON — using default")
        return _build_result(DEFAULT_INTERVAL)

    if unit not in VALID_UNITS or not (1 <= value <= 365):
        logger.warning("Scheduler returned invalid interval %d %s — using default", value, unit)
        return _build_result(DEFAULT_INTERVAL)

    return _build_result({"value": value, "unit": unit})


def _build_result(interval: dict) -> ScheduleResult:
    value, unit = interval["value"], interval["unit"]
    if unit == "days":
        delta = timedelta(days=value)
    elif unit == "weeks":
        delta = timedelta(weeks=value)
    else:  # months
        delta = timedelta(days=value * 30)
    return ScheduleResult(value=value, unit=unit, next_check_at=datetime.utcnow() + delta)
