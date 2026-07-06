"""Agent org chart — must be JSON-serialisable (slotted dataclasses have no
``__dict__``; regression guard for the /agents/org 500)."""

from __future__ import annotations

import json

from us_watcher.domain.agents.catalog import DESKS, SPECIALISTS, SUPERVISORS, org_chart


def test_org_chart_is_json_serialisable():
    chart = org_chart()
    # Would raise TypeError if any value (e.g. a raw AgentSpec) were not encodable.
    json.dumps(chart)


def test_org_chart_shape_matches_catalog():
    chart = org_chart()
    assert chart["specialist_count"] == len(SPECIALISTS)
    assert chart["supervisor_count"] == len(SUPERVISORS)
    assert len(chart["desks"]) == len(DESKS)
    # Each supervisory/desk agent is a plain dict with the expected fields.
    for sup in chart["supervisory"]:
        assert {"id", "name", "desk", "category", "scope"} <= set(sup)
    for desk in chart["desks"]:
        for agent in desk["agents"]:
            assert isinstance(agent, dict) and "id" in agent
