import json
import time
from io import BytesIO
from typing import Any
from urllib.parse import urlparse

import httpx

from ai.config import settings
from ai.models.pdf_summary_models import (
    HormonalPanelSummary,
    HormoneAiInsights,
    HormoneBiomarker,
    HormoneBiomarkers,
    HormoneNextSteps,
    PdfSummaryRequest,
    PdfSummaryResponse,
)
from ai.utils.llm_call import llm_call


RETRYABLE_LLM_STATUS_CODES = {429, 500, 502, 503, 529}
LLM_RETRY_DELAYS_SECONDS = (1.0, 2.0)
MAX_PDF_TEXT_CHARS = 18000
NEEDS_ATTENTION_BIOMARKERS = ("Estradiol (E2)", "Cortisol AM")
NORMAL_RESULT_BIOMARKERS = ("Progesterone", "FSH", "LH")


HORMONE_PANEL_SYSTEM_PROMPT = """You are a careful lab-report analysis assistant for a hormone panel UI.

Rules:
- Analyze only the lab report text provided.
- Do not diagnose, prescribe, or claim medical certainty.
- Use the report's actual values and reference ranges when present.
- If a value is missing, write "Not found" and explain that it was not available in the report text.
- Return valid JSON only. Do not add markdown, code fences, or extra commentary.
"""


def summarize_pdf(request: PdfSummaryRequest | None = None) -> PdfSummaryResponse:
    report_id = request.report_id if request else None
    pdf_content, content_type, source, resolved_report_id = fetch_backend_pdf(report_id)
    report_text = _extract_pdf_text(pdf_content)
    summary = _generate_hormonal_panel_summary(report_text)

    return PdfSummaryResponse(
        report_id=resolved_report_id,
        source_path=source,
        content_type=content_type,
        file_size_bytes=len(pdf_content),
        text_extracted=bool(report_text.strip()),
        summary=summary,
    )


def fetch_backend_pdf(report_id: int | None = None) -> tuple[bytes, str, str, int | None]:
    source = settings.LAB_REPORTS_URL
    response = _get_backend_response(source)
    content_type = response.headers.get("content-type", "application/octet-stream")
    content = response.content

    if _is_pdf_response(content_type, content):
        return content, content_type, source, report_id

    if "json" not in content_type.lower():
        raise ValueError("Backend route did not return a PDF file")

    pdf_source, resolved_report_id = _extract_pdf_source(response.json(), report_id)
    pdf_response = _get_backend_response(pdf_source)
    pdf_content_type = pdf_response.headers.get("content-type", "application/octet-stream")
    pdf_content = pdf_response.content

    if not _is_pdf_response(pdf_content_type, pdf_content):
        raise ValueError("Backend lab report link did not return a PDF file")

    return pdf_content, pdf_content_type, pdf_source, resolved_report_id


def _generate_hormonal_panel_summary(report_text: str) -> HormonalPanelSummary:
    if not report_text.strip():
        return _fallback_panel_summary()

    prompt = _build_hormone_panel_prompt(report_text)
    response_text = _call_summary_llm(prompt)
    parsed = _parse_summary_response(response_text)
    if parsed:
        return parsed

    return _fallback_panel_summary(report_text)


def _build_hormone_panel_prompt(report_text: str) -> str:
    clipped_text = report_text[:MAX_PDF_TEXT_CHARS]
    return f"""Analyze this lab report text and generate a Hormonal Panel response.

Lab report text:
{clipped_text}

Return JSON with exactly this structure:
{{
  "panel": "Hormonal Panel",
  "biomarkers": {{
    "needs_attention": [
      {{"name": "Estradiol (E2)", "value": "...", "reference_range": "...", "status": "High", "interpretation": "..."}},
      {{"name": "Cortisol AM", "value": "...", "reference_range": "...", "status": "Borderline", "interpretation": "..."}}
    ],
    "normal_results": [
      {{"name": "Progesterone", "value": "...", "reference_range": "...", "status": "Normal", "interpretation": "..."}},
      {{"name": "FSH", "value": "...", "reference_range": "...", "status": "Normal", "interpretation": "..."}},
      {{"name": "LH", "value": "...", "reference_range": "...", "status": "Normal", "interpretation": "..."}}
    ]
  }},
  "ai_insights": {{
    "cross_data_context": ["...", "...", "..."],
    "estradiol_elevation": "...",
    "cortisol_near_ceiling": "...",
    "hormonal_balance": "..."
  }},
  "next_steps": {{
    "recommendations": ["...", "...", "...", "..."],
    "medical_disclaimer": "..."
  }}
}}

Requirements:
- Needs attention must include exactly Estradiol (E2) and Cortisol AM.
- Normal results must include exactly Progesterone, FSH, and LH.
- Cross data context should connect the hormone values to broader report context when available.
- Next steps should be practical, cautious recommendations.
- Include a medical disclaimer that this is not medical advice and a clinician should interpret abnormal results.
"""


def _call_summary_llm(prompt: str) -> str:
    attempts = len(LLM_RETRY_DELAYS_SECONDS) + 1

    for attempt in range(attempts):
        try:
            return llm_call(
                prompt=prompt,
                system=HORMONE_PANEL_SYSTEM_PROMPT,
                max_tokens=2400,
            )
        except Exception as exc:
            is_last_attempt = attempt == attempts - 1
            if not _is_retryable_llm_error(exc):
                raise
            if is_last_attempt:
                return ""
            time.sleep(LLM_RETRY_DELAYS_SECONDS[attempt])

    return ""


def _parse_summary_response(text: str) -> HormonalPanelSummary | None:
    if not text:
        return None

    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(line for line in lines if not line.startswith("```")).strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        payload = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None

    try:
        payload = _coerce_summary_payload(payload)
        return _normalize_panel_summary(HormonalPanelSummary.model_validate(payload))
    except Exception:
        return None


def _coerce_summary_payload(payload: Any) -> dict:
    if not isinstance(payload, dict):
        return {}

    coerced = dict(payload)
    coerced["panel"] = "Hormonal Panel"
    coerced["biomarkers"] = _coerce_biomarkers(coerced.get("biomarkers"))
    coerced["ai_insights"] = _coerce_ai_insights(coerced.get("ai_insights"))
    coerced["next_steps"] = _coerce_next_steps(coerced.get("next_steps"))
    return coerced


def _coerce_biomarkers(value: Any) -> dict:
    if isinstance(value, dict):
        needs_attention = value.get("needs_attention") or []
        normal_results = value.get("normal_results") or []
    elif isinstance(value, list):
        needs_attention = [
            item for item in value
            if _biomarker_key(str(item.get("name", ""))) in {"estradiole2", "estradiol", "cortisolam", "cortisol"}
        ]
        normal_results = [
            item for item in value
            if _biomarker_key(str(item.get("name", ""))) in {"progesterone", "fsh", "lh"}
        ]
    else:
        needs_attention = []
        normal_results = []

    return {
        "needs_attention": [_coerce_biomarker(item) for item in needs_attention],
        "normal_results": [_coerce_biomarker(item) for item in normal_results],
    }


def _coerce_biomarker(value: Any) -> dict:
    if not isinstance(value, dict):
        return {
            "name": "Not found",
            "value": "Not found",
            "reference_range": "Not found",
            "status": "Not found",
            "interpretation": "Not found in the extracted lab report text.",
        }

    raw_value = value.get("value", "Not found")
    unit = value.get("unit")
    if raw_value is None:
        display_value = "Not found"
    elif unit:
        display_value = f"{raw_value} {unit}"
    else:
        display_value = str(raw_value)

    interpretation = value.get("interpretation") or value.get("note") or value.get("summary")
    if not interpretation:
        interpretation = "Review this result with the lab reference range and clinical context."

    return {
        "name": str(value.get("name") or "Not found"),
        "value": display_value,
        "reference_range": str(value.get("reference_range") or "Not found"),
        "status": str(value.get("status") or "Not found"),
        "interpretation": str(interpretation),
    }


def _coerce_ai_insights(value: Any) -> dict:
    if isinstance(value, dict):
        cross_data_context = value.get("cross_data_context") or []
        if isinstance(cross_data_context, str):
            cross_data_context = [cross_data_context]
        return {
            "cross_data_context": [str(item) for item in cross_data_context],
            "estradiol_elevation": str(value.get("estradiol_elevation") or "Estradiol should be interpreted against cycle timing and the lab reference range."),
            "cortisol_near_ceiling": str(value.get("cortisol_near_ceiling") or "Cortisol AM was not clearly available or should be interpreted with symptoms and timing."),
            "hormonal_balance": str(value.get("hormonal_balance") or "Review estradiol, progesterone, FSH, LH, and cortisol together for overall context."),
        }

    context = [str(value)] if value else []
    return {
        "cross_data_context": context,
        "estradiol_elevation": "Estradiol should be interpreted against cycle timing and the lab reference range.",
        "cortisol_near_ceiling": "Cortisol AM was not clearly available or should be interpreted with symptoms and timing.",
        "hormonal_balance": "Review estradiol, progesterone, FSH, LH, and cortisol together for overall context.",
    }


def _coerce_next_steps(value: Any) -> dict:
    disclaimer = (
        "This AI summary is for informational purposes only and is not medical advice. "
        "A qualified healthcare professional should interpret abnormal or concerning lab results."
    )
    if isinstance(value, dict):
        recommendations = value.get("recommendations") or []
        if isinstance(recommendations, str):
            recommendations = [recommendations]
        return {
            "recommendations": [str(item) for item in recommendations],
            "medical_disclaimer": str(value.get("medical_disclaimer") or disclaimer),
        }
    if isinstance(value, list):
        return {
            "recommendations": [str(item) for item in value],
            "medical_disclaimer": disclaimer,
        }
    return {
        "recommendations": [],
        "medical_disclaimer": disclaimer,
    }

def _normalize_panel_summary(summary: HormonalPanelSummary) -> HormonalPanelSummary:
    fallback = _fallback_panel_summary()
    summary.biomarkers.needs_attention = _ordered_biomarkers(
        summary.biomarkers.needs_attention,
        NEEDS_ATTENTION_BIOMARKERS,
        fallback.biomarkers.needs_attention,
    )
    summary.biomarkers.normal_results = _ordered_biomarkers(
        summary.biomarkers.normal_results,
        NORMAL_RESULT_BIOMARKERS,
        fallback.biomarkers.normal_results,
    )
    return summary


def _ordered_biomarkers(
    biomarkers: list[HormoneBiomarker],
    expected_names: tuple[str, ...],
    fallback_biomarkers: list[HormoneBiomarker],
) -> list[HormoneBiomarker]:
    ordered = []
    for index, expected_name in enumerate(expected_names):
        match = _find_biomarker(biomarkers, expected_name)
        ordered.append(match or fallback_biomarkers[index])
    return ordered


def _find_biomarker(
    biomarkers: list[HormoneBiomarker],
    expected_name: str,
) -> HormoneBiomarker | None:
    expected_key = _biomarker_key(expected_name)
    for biomarker in biomarkers:
        candidate_key = _biomarker_key(biomarker.name)
        if expected_key in candidate_key or candidate_key in expected_key:
            biomarker.name = expected_name
            return biomarker
    return None


def _biomarker_key(name: str) -> str:
    return "".join(char for char in name.lower() if char.isalnum())


def _extract_pdf_text(pdf_content: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("Install pypdf to extract lab report text from PDFs") from exc

    reader = PdfReader(BytesIO(pdf_content))
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")

    return "\n\n".join(page for page in pages if page).strip()


def _get_backend_response(path: str) -> httpx.Response:
    url = _backend_url(path)

    response = httpx.get(url, headers=_backend_headers(), timeout=30.0, follow_redirects=True)
    response.raise_for_status()
    return response


def _backend_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "ngrok-skip-browser-warning": "true",
    }

    if settings.BACKEND_ACCESS_TOKEN:
        headers["Authorization"] = f"Bearer {settings.BACKEND_ACCESS_TOKEN}"
        headers["access-token"] = settings.BACKEND_ACCESS_TOKEN
        headers["x-access-token"] = settings.BACKEND_ACCESS_TOKEN

    return headers


def _is_pdf_response(content_type: str, content: bytes) -> bool:
    return "application/pdf" in content_type.lower() or content.startswith(b"%PDF")


def _extract_pdf_source(payload: Any, report_id: int | None = None) -> tuple[str, int | None]:
    candidates: list[tuple[str, int | None]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            pdf_source = _pdf_source_from_record(value)
            candidate_id = _extract_report_id(value)
            if pdf_source:
                candidates.append((pdf_source, candidate_id))

            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)

    if report_id is not None:
        for candidate, candidate_id in candidates:
            if candidate_id == report_id:
                return candidate, candidate_id
        raise ValueError(f"Backend lab reports response did not include lab report id {report_id}")

    for candidate, candidate_id in candidates:
        if ".pdf" in candidate.lower():
            return candidate, candidate_id
    if candidates:
        return candidates[0]

    raise ValueError("Backend lab reports response did not include a PDF link")


def _pdf_source_from_record(record: dict) -> str | None:
    preferred: list[str] = []
    fallback: list[str] = []

    for key, child in record.items():
        key_name = str(key).lower()
        if not isinstance(child, str):
            continue
        if not any(marker in key_name for marker in ("lab_report", "pdf", "file", "url", "path", "document")):
            continue
        if ".pdf" in child.lower():
            preferred.append(child)
        else:
            fallback.append(child)

    if preferred:
        return preferred[0]
    if fallback:
        return fallback[0]
    return None


def _extract_report_id(record: dict) -> int | None:
    for key in ("id", "lab_report_id", "report_id"):
        value = record.get(key)
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _backend_url(path: str) -> str:
    cleaned = path.strip()
    if not cleaned:
        raise ValueError("Backend path is required")
    if cleaned.startswith(("http://", "https://")):
        if not _is_allowed_backend_url(cleaned):
            raise ValueError("Full URLs are only allowed for configured lab report resources")
        return cleaned

    normalized_path = _normalize_backend_path(cleaned)
    if normalized_path.startswith("/storage/"):
        return f"{_lab_reports_origin()}{normalized_path}"
    return f"{settings.BACKEND_URL.rstrip('/')}{normalized_path}"


def _is_allowed_backend_url(url: str) -> bool:
    if url == settings.LAB_REPORTS_URL:
        return True

    parsed = urlparse(url)
    lab_reports = urlparse(settings.LAB_REPORTS_URL)
    return (
        parsed.scheme in {"http", "https"}
        and parsed.netloc == lab_reports.netloc
        and parsed.path.startswith("/storage/")
        and parsed.path.lower().endswith(".pdf")
    )


def _lab_reports_origin() -> str:
    parsed = urlparse(settings.LAB_REPORTS_URL)
    return f"{parsed.scheme}://{parsed.netloc}"


def _normalize_backend_path(path: str) -> str:
    if not path.startswith("/"):
        return f"/{path}"
    return path


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


def _fallback_panel_summary(report_text: str = "") -> HormonalPanelSummary:
    missing_note = "Not found in the extracted lab report text."
    source_note = "The PDF was fetched, but AI summary generation could not complete."
    if report_text:
        source_note = "Review the extracted report values with your clinician for interpretation."

    return HormonalPanelSummary(
        biomarkers=HormoneBiomarkers(
            needs_attention=[
                HormoneBiomarker(
                    name="Estradiol (E2)",
                    value="Not found",
                    reference_range="Not found",
                    status="Needs attention",
                    interpretation=missing_note,
                ),
                HormoneBiomarker(
                    name="Cortisol AM",
                    value="Not found",
                    reference_range="Not found",
                    status="Needs attention",
                    interpretation=missing_note,
                ),
            ],
            normal_results=[
                HormoneBiomarker(
                    name="Progesterone",
                    value="Not found",
                    reference_range="Not found",
                    status="Normal",
                    interpretation=missing_note,
                ),
                HormoneBiomarker(
                    name="FSH",
                    value="Not found",
                    reference_range="Not found",
                    status="Normal",
                    interpretation=missing_note,
                ),
                HormoneBiomarker(
                    name="LH",
                    value="Not found",
                    reference_range="Not found",
                    status="Normal",
                    interpretation=missing_note,
                ),
            ],
        ),
        ai_insights=HormoneAiInsights(
            cross_data_context=[source_note],
            estradiol_elevation="Estradiol needs clinician review when elevated or out of range.",
            cortisol_near_ceiling="Morning cortisol should be interpreted against the lab reference range and symptoms.",
            hormonal_balance="Progesterone, FSH, LH, estradiol, and cortisol should be reviewed together rather than in isolation.",
        ),
        next_steps=HormoneNextSteps(
            recommendations=[
                "Discuss the hormone panel with your healthcare provider.",
                "Confirm whether results align with your cycle day and symptoms.",
                "Ask whether repeat testing or follow-up labs are appropriate.",
            ],
            medical_disclaimer=(
                "This AI summary is for informational purposes only and is not medical advice. "
                "A qualified healthcare professional should interpret abnormal or concerning lab results."
            ),
        ),
    )
