"""Unit tests for the HierarchyResolver tier authority."""

from __future__ import annotations

from types import SimpleNamespace

from epic_report_generator.core.data_models import HierarchyNode
from epic_report_generator.core.hierarchy import HierarchyResolver


def _chain() -> list[HierarchyNode]:
    # Epic(0) → Story(1, parent) + Bug(1, link) → Sub-task(2, parent)
    return [
        HierarchyNode(issue_type_id="E", issue_type="Epic", display_tier=0),
        HierarchyNode(issue_type_id="S", issue_type="Story", display_tier=1),
        HierarchyNode(
            issue_type_id="B",
            issue_type="Bug",
            edge="link",
            link_types=["Blocks"],
            display_tier=1,
        ),
        HierarchyNode(issue_type_id="T", issue_type="Sub-task", display_tier=2),
    ]


def _issue(type_id: str, name: str = ""):
    return SimpleNamespace(issue_type_id=type_id, issue_type=name)


def test_node_of_matches_by_id_then_name():
    r = HierarchyResolver(_chain())
    assert r.node_of("S").issue_type == "Story"  # by id
    assert r.node_of("", "Story").issue_type == "Story"  # by name fallback
    assert r.node_of("nope", "nope") is None  # off-chain → None (drop relies on it)


def test_id_takes_precedence_over_name():
    # A row whose id is Story but whose (stale) name is Bug resolves by id.
    r = HierarchyResolver(_chain())
    assert r.node_of("S", "Bug").issue_type == "Story"


def test_tier_of_and_exclusion():
    r = HierarchyResolver(_chain())
    assert r.tier_of("E") == 0
    assert r.tier_of("S") == 1
    assert r.tier_of("T") == 2
    assert r.tier_of("ZZ") is None  # excluded type
    assert r.is_excluded("ZZ") is True
    assert r.is_excluded("T") is False


def test_node_of_issue_reads_both_fields():
    r = HierarchyResolver(_chain())
    assert r.node_of_issue(_issue("T", "Sub-task")).display_tier == 2
    assert r.node_of_issue(_issue("", "Story")).display_tier == 1
    assert r.node_of_issue(_issue("X", "X")) is None


def test_nodes_at_and_child_nodes_of():
    r = HierarchyResolver(_chain())
    assert {n.issue_type for n in r.nodes_at(1)} == {"Story", "Bug"}
    # Children of the Epic tier are the tier-1 nodes (Story + Bug), edges intact.
    children = r.child_nodes_of(0)
    assert {n.issue_type for n in children} == {"Story", "Bug"}
    assert any(n.edge == "link" and n.link_types == ["Blocks"] for n in children)
    assert {n.issue_type for n in r.child_nodes_of(1)} == {"Sub-task"}
    assert r.child_nodes_of(2) == []  # nothing below Sub-task


def test_id_only_dialog_path():
    # The customize dialog has only (key, type_id) — no name — and must still resolve.
    r = HierarchyResolver(_chain())
    assert r.tier_of("S") == 1
    assert r.tier_of("T") == 2
    assert r.tier_of("E") == 0


def test_empty_chain_resolves_nothing():
    r = HierarchyResolver([])
    assert r.node_of("S") is None
    assert r.tier_of("S") is None
    assert r.nodes_at(0) == []
    assert r.child_nodes_of(0) == []
