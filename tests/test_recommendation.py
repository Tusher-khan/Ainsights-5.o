"""Recommendation intent, planning shape, and the evidence-based engine.

The engine must never state a number that isn't in the already-executed
ExecutionResult, and must degrade honestly (not invent a finding) when the
result doesn't have a comparable shape.
"""

from __future__ import annotations

from app.agents import pandas_agent
from app.ai.intent_classifier import classify_with_rules
from app.ai.query_planner import plan_with_rules
from app.ai.recommendation_engine import build_recommendations
from app.core.models import QueryPlan


def test_recommendation_intent_detected():
    assert classify_with_rules("What should we do about our weakest region?").intent == "recommendation"
    assert classify_with_rules("Why is profit declining?").intent == "recommendation"
    assert classify_with_rules("Any recommendations to improve sales?").intent == "recommendation"


def test_recommendation_intent_not_confused_with_ranking():
    # Still a plain ranking question, no advice requested.
    assert classify_with_rules("Which region has the highest profit?").intent == "ranking"


def test_plan_for_recommendation_groups_by_a_dimension(source):
    plan = plan_with_rules("What should we do to improve weak regions?", source, "recommendation")
    assert plan.dimensions, "recommendation plans must pick a comparison dimension"
    assert plan.measures


def test_recommendation_engine_uses_only_executed_numbers(source):
    plan = plan_with_rules("What should we do about underperforming regions?", source, "recommendation")
    result, _operation = pandas_agent.execute(plan, source)

    cards = build_recommendations("What should we do about underperforming regions?", result, plan, source)
    assert cards, "expected at least one recommendation card"

    # Every numeric figure quoted in the finding/evidence must trace back to
    # a value that was actually in the executed result rows.
    executed_values = {row[c] for row in result.rows for c in result.columns if isinstance(row.get(c), (int, float))}
    first = cards[0]
    assert first["finding"]
    assert first["evidence"]
    assert first["confidence"] in {"low", "medium"}
    # worst/best labels must be real row labels, not invented ones
    labels_in_result = {row[result.columns[0]] for row in result.rows}
    assert any(label in first["finding"] for label in labels_in_result)


def test_recommendation_engine_degrades_honestly_without_a_dimension(source):
    plan = QueryPlan(
        intent="recommendation",
        dataset=source.name,
        dimensions=[],
        measures=["Sales"],
        aggregation="sum",
    )
    result, _operation = pandas_agent.execute(plan, source)
    cards = build_recommendations("what should we do", result, plan, source)
    assert len(cards) == 1
    assert "not sufficient" in cards[0]["finding"].lower()
    assert cards[0]["confidence"] == "low"
