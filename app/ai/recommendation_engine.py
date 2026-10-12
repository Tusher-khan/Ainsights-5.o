"""Evidence-based recommendations.

This is deliberately NOT another LLM call that free-associates business
advice. Every number in a recommendation comes from the `ExecutionResult`
that has already been validated by `validation_agent.validate_result` —
the same result the headline answer is built from. This module only
*arranges* those already-verified numbers into a Finding / Evidence /
Possible explanation / Recommendation / Measurement / Confidence structure,
and it is explicit about the difference between an observed pattern and a
caused one.

What this does NOT do, by design:
  - It never computes a new number outside the executed result.
  - It never asserts a cause ("sales are low BECAUSE ..."); at most it
    names an associated column as something worth investigating.
  - It never promises a financial outcome ("this will increase revenue
    by X%") — there is no basis for that claim in a single grouped query.

If the executed result does not have the shape a recommendation needs
(no dimension to compare across, or too few rows), it says so honestly
instead of inventing a finding.
"""

from __future__ import annotations

from app.core.datasource import DataSource
from app.core.models import ExecutionResult, QueryPlan
from app.utils.helpers import human_number
from app.utils.logger import get_logger

log = get_logger("ai.recommendation")

MIN_GROUPS_FOR_COMPARISON = 2


def _readable(column: str) -> str:
    return column.replace("_", " ").strip().title()


def build_recommendations(
    question: str, result: ExecutionResult, plan: QueryPlan, source: DataSource
) -> list[dict]:
    """Return 0-2 evidence-based recommendation cards from an already-executed result.

    Each card: finding, evidence, explanation, recommendation, measurement,
    confidence ("low" | "medium"), limitations.
    """
    if not plan.dimensions or not plan.measures:
        return [
            {
                "finding": "The available data is not sufficient to compare performance across a category.",
                "evidence": "This question did not resolve to a measure grouped by a category, which a "
                "recommendation needs as a baseline for comparison.",
                "explanation": None,
                "recommendation": "Ask a more specific question that names what to compare, e.g. "
                f"\"which {(source.dimensions[0] if source.dimensions else 'category')} has the lowest "
                f"{(source.measures[0] if source.measures else 'value')}?\"",
                "measurement": None,
                "confidence": "low",
                "limitations": "No grouped comparison was available to base a recommendation on.",
            }
        ]

    rows = result.rows or []
    dimension = plan.dimensions[0]
    measure = plan.measures[0]
    value_key = next((c for c in result.columns if c not in plan.dimensions), result.columns[-1] if result.columns else measure)
    label_key = dimension if dimension in result.columns else (result.columns[0] if result.columns else dimension)

    numeric_rows = [
        r for r in rows
        if isinstance(r.get(value_key), (int, float)) and r.get(label_key) is not None
    ]

    if len(numeric_rows) < MIN_GROUPS_FOR_COMPARISON:
        return [
            {
                "finding": f"Only {len(numeric_rows)} group(s) of '{_readable(dimension)}' had a usable "
                f"value for '{_readable(measure)}'.",
                "evidence": f"The executed query returned {result.row_count} row(s).",
                "explanation": None,
                "recommendation": "At least two groups are needed to identify a best or worst performer. "
                "Try broadening the question or checking for missing data in this column.",
                "measurement": None,
                "confidence": "low",
                "limitations": "Not enough comparable groups in the result to support a recommendation.",
            }
        ]

    sorted_rows = sorted(numeric_rows, key=lambda r: r[value_key], reverse=True)
    best, worst = sorted_rows[0], sorted_rows[-1]
    total = sum(r[value_key] for r in numeric_rows)
    best_share = (best[value_key] / total * 100) if total else 0

    cards: list[dict] = []

    # --- Card 1: the gap between best and worst ---
    gap = best[value_key] - worst[value_key]
    gap_pct = (gap / best[value_key] * 100) if best[value_key] else 0
    explanation = None
    other_dims = [d for d in source.dimensions if d != dimension][:2]
    if other_dims:
        explanation = (
            f"This is an observed difference, not a proven cause. If a deeper explanation is needed, "
            f"compare '{worst[label_key]}' and '{best[label_key]}' across other available columns such as "
            f"{', '.join(_readable(d) for d in other_dims)} — the data alone does not say why the gap exists."
        )
    cards.append(
        {
            "finding": f"'{worst[label_key]}' has the lowest {_readable(measure)} "
            f"({human_number(worst[value_key])}) among the {len(numeric_rows)} "
            f"{_readable(dimension)} groups compared, versus '{best[label_key]}' at "
            f"{human_number(best[value_key])}.",
            "evidence": f"Calculated as {plan.aggregation.upper()}({_readable(measure)}) grouped by "
            f"{_readable(dimension)}, executed against {source.name}. Gap: "
            f"{human_number(gap)} ({round(gap_pct, 1)}% lower than the top performer).",
            "explanation": explanation,
            "recommendation": f"Investigate '{worst[label_key]}' specifically — review what '{best[label_key]}' "
            f"is doing differently, and check whether the gap is recent or long-standing by asking a "
            f"follow-up trend question for these two groups.",
            "measurement": f"Track {_readable(measure)} for '{worst[label_key]}' over the next reporting "
            f"period and compare its rate of change against '{best[label_key]}'.",
            "confidence": "medium" if len(numeric_rows) >= 4 else "low",
            "limitations": "Based on a single snapshot of the current data; no time-series or causal "
            "evidence is available from this query alone.",
        }
    )

    # --- Card 2: concentration risk, only if meaningfully concentrated ---
    if best_share >= 35 and len(numeric_rows) >= 3:
        cards.append(
            {
                "finding": f"'{best[label_key]}' accounts for {round(best_share, 1)}% of total "
                f"{_readable(measure)} across the {len(numeric_rows)} groups shown.",
                "evidence": f"{human_number(best[value_key])} of {human_number(total)} total "
                f"{_readable(measure)} ({round(best_share, 1)}%).",
                "explanation": "A single group carrying over a third of the total is a concentration "
                "pattern, not necessarily a problem — but it is worth knowing before making plans that "
                "assume performance is evenly spread.",
                "recommendation": f"Treat '{best[label_key]}' as a key dependency: confirm what is driving "
                f"its share before assuming the other {len(numeric_rows) - 1} groups can be scaled the "
                f"same way, and consider whether that concentration is a risk if '{best[label_key]}' "
                f"changes.",
                "measurement": f"Monitor {_readable(measure)} share for '{best[label_key]}' each period; "
                f"a falling share with flat totals signals other groups catching up, a rising share "
                f"signals increasing concentration.",
                "confidence": "medium",
                "limitations": "Concentration is observed, not diagnosed — the data does not say whether "
                "this is healthy or risky for this business.",
            }
        )

    return cards[:2]
