import json
import logging
import time
from dataclasses import dataclass, field

from openai import OpenAI

logger = logging.getLogger(__name__)

VALID_VERDICTS = {"unresolved", "came_true", "came_false"}
MAX_SOURCES = 5
MAX_RETRIES = 3

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


@dataclass
class InvestigationResult:
    verdict: str
    summary: str
    sources: list[dict[str, str]] = field(default_factory=list)


def investigate(prediction_text: str, collection_name: str) -> InvestigationResult:
    """Investigate a prediction using web search. Retries up to MAX_RETRIES times."""
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            research = _search_web(prediction_text, collection_name)
            extraction = _extract_structured(prediction_text, research)
            return _build_result(extraction)
        except Exception as exc:
            last_error = exc
            wait = 2 ** attempt
            logger.warning("Investigator attempt %d/%d failed: %s — retrying in %ds", attempt + 1, MAX_RETRIES, exc, wait)
            time.sleep(wait)

    raise RuntimeError(f"Investigator failed after {MAX_RETRIES} attempts") from last_error


def _search_web(prediction_text: str, collection_name: str) -> str:
    """Step 1: Use OpenAI Responses API + web_search_preview to gather evidence."""
    prompt = (
        f"You are fact-checking a prediction from '{collection_name}'.\n\n"
        f"PREDICTION: <<< {prediction_text} >>>\n\n"
        "Search the web to find current evidence for or against this prediction. "
        "Gather information from 3-5 reliable sources. "
        "Report what you find, including source URLs and titles."
    )

    response = _get_client().responses.create(
        model="gpt-4.1",
        tools=[{"type": "web_search_preview"}],
        input=[{"role": "user", "content": prompt}],
    )

    for item in response.output:
        if item.type == "message":
            for content in item.content:
                if content.type == "output_text":
                    return content.text

    raise ValueError("No text output from web search response")


def _extract_structured(prediction_text: str, research_text: str) -> dict:
    """Step 2: Use Chat Completions + JSON mode to extract structured verdict from research text."""
    system = (
        "You extract structured fact-check results from research text. "
        "Return valid JSON with exactly these fields:\n"
        '- "verdict": one of "came_true", "came_false", "unresolved"\n'
        '- "summary": 1-2 sentence explanation of your verdict\n'
        '- "sources": array of up to 5 objects, each with "url", "title", "relevance_summary" (1-2 sentences)\n\n'
        "Only return JSON, no other text."
    )
    user = (
        f"PREDICTION: <<< {prediction_text} >>>\n\n"
        f"RESEARCH FINDINGS:\n{research_text}\n\n"
        "Extract the structured verdict."
    )

    response = _get_client().chat.completions.create(
        model="gpt-4.1",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )

    return json.loads(response.choices[0].message.content)


def _build_result(extraction: dict) -> InvestigationResult:
    verdict = extraction.get("verdict", "unresolved")
    if verdict not in VALID_VERDICTS:
        logger.warning("Invalid verdict '%s' — defaulting to unresolved", verdict)
        verdict = "unresolved"

    summary = extraction.get("summary", "No summary available.")
    sources = extraction.get("sources", [])[:MAX_SOURCES]

    return InvestigationResult(verdict=verdict, summary=summary, sources=sources)
