"""Pure score normalization and official-total policy."""

from __future__ import annotations

from typing import Any


WEIGHTS = {"D1": 0.20, "D2": 0.50, "D3": 0.15, "D4": 0.15}
RESCORE_STATUSES = frozenset(
    {"judge_output_unavailable", "completed_with_judge_gap", "needs_rescore"}
)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _d3_score(detail: dict[str, Any]) -> float | None:
    if detail.get("status") != "completed":
        return None
    value = _number(detail.get("score"))
    if value is not None:
        maximum = _number(detail.get("max_score"))
        return value * 100.0 if maximum == 1.0 else value
    value = _number(detail.get("score_normalized"))
    if value is not None:
        return value * 100.0
    return None


def assemble_result(
    *,
    game: str,
    model: str,
    repetition: int,
    candidate_project_sha256: str,
    d4_configured: bool,
    d1_detail: dict[str, Any],
    d2_detail: dict[str, Any] | None,
    d3_detail: dict[str, Any],
    d4_detail: dict[str, Any] | None,
) -> dict[str, Any]:
    d1 = _number(d1_detail.get("score")) or 0.0
    gate = bool(d1_detail.get("gate_pass"))

    if d2_detail is not None:
        raw_d2 = _number(d2_detail.get("score"))
        d2 = None if raw_d2 is None else (raw_d2 * 100.0 if raw_d2 <= 1.0 else raw_d2)
        d2_status = str(d2_detail.get("status") or "completed")
    else:
        d2 = None
        d2_status = "incomplete"

    d3 = _d3_score(d3_detail)
    diagnostic = _number(d3_detail.get("diagnostic_score"))
    if diagnostic is None:
        diagnostic = _number(d3_detail.get("tool_diagnostic_score"))

    if not d4_configured:
        d4 = None
        d4_status = "not_configured"
    elif d4_detail is None:
        d4 = None
        d4_status = "incomplete"
    else:
        raw_d4 = _number(d4_detail.get("score_normalized"))
        if raw_d4 is None:
            public = _number(d4_detail.get("score"))
            maximum = _number(d4_detail.get("max_score"))
            raw_d4 = public / maximum if public is not None and maximum else None
        d4 = None if raw_d4 is None else raw_d4 * 100.0
        d4_status = str(d4_detail.get("status") or "completed")

    contributions: dict[str, float | None] = {
        "D1": d1 * WEIGHTS["D1"],
        "D2": (d2 * WEIGHTS["D2"] if gate and d2 is not None else 0.0),
        "D3": (d3 * WEIGHTS["D3"] if gate and d3 is not None else (0.0 if not gate else None)),
        "D4": (
            None
            if not d4_configured
            else (
                0.0
                if not gate
                else (None if d4 is None else d4 * WEIGHTS["D4"])
            )
        ),
    }

    has_rescore_gap = d2_status in RESCORE_STATUSES or d4_status in RESCORE_STATUSES
    if has_rescore_gap:
        official_total: float | None = None
    elif not d4_configured:
        official_total: float | None = None
    elif not gate:
        official_total = round(contributions["D1"] or 0.0, 6)
    elif any(value is None for value in (d2, d3, d4)):
        official_total = None
    else:
        official_total = round(
            d1 * WEIGHTS["D1"]
            + d2 * WEIGHTS["D2"]
            + d3 * WEIGHTS["D3"]
            + d4 * WEIGHTS["D4"],
            6,
        )

    result_status = "needs_rescore" if has_rescore_gap else "completed"
    return {
        "schema_version": 1,
        "task": {
            "game": game,
            "model": model,
            "repetition": repetition,
            "candidate_project_sha256": candidate_project_sha256,
        },
        "dimensions": {
            "D1": {
                "status": "completed",
                "score": d1,
                "gate_pass": gate,
                "weighted_contribution": contributions["D1"],
                "detail": d1_detail,
            },
            "D2": {
                "status": d2_status,
                "score": d2,
                **(
                    {"diagnostic_measured_despite_d1_gate": True}
                    if not gate and d2_detail is not None
                    else {}
                ),
                "weighted_contribution": contributions["D2"],
                "detail": d2_detail,
            },
            "D3": {
                "status": str(d3_detail.get("status") or "incomplete"),
                "score": d3,
                "diagnostic_score": diagnostic,
                **(
                    {"diagnostic_measured_despite_d1_gate": True}
                    if not gate
                    else {}
                ),
                "weighted_contribution": contributions["D3"],
                "detail": d3_detail,
            },
            "D4": {
                "status": d4_status,
                "score": d4,
                **(
                    {"diagnostic_measured_despite_d1_gate": True}
                    if not gate and d4_configured and d4_detail is not None
                    else {}
                ),
                "weighted_contribution": contributions["D4"],
                "detail": d4_detail,
            },
        },
        "official_total": official_total,
        "status": result_status,
        "formula": (
            "Final = 0.20*D1 + Gate_D1*(0.50*D2 + 0.15*D3 + 0.15*D4); "
            "D2-D4 are measured regardless of the D1 gate when valid evidence is available; "
            "games without configured D4 have no official total and weights are not renormalized"
        ),
        "weights": WEIGHTS,
    }
