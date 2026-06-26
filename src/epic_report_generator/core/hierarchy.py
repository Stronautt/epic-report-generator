"""Single tier-resolution authority for the issue hierarchy.

One :class:`HierarchyResolver`, built from a profile's ``list[HierarchyNode]``,
answers every "what tier is this issue / is it on-chain / what sits a tier down"
question.  It replaces the id-then-name match that used to be written three times
(``JiraClient.apply_hierarchy``'s inner ``node_of``, ``JiraClient._issue_matches_node``,
and ``config_panel._included_children``) so the report fetch, the customize dialog,
and the override resolution all agree.  Pure — no Qt, no network.
"""

from __future__ import annotations

from typing import Protocol

from .data_models import HierarchyNode


class _Typed(Protocol):
    """The minimal issue shape the resolver reads (a ``JiraIssue`` satisfies it)."""

    issue_type_id: str
    issue_type: str


class HierarchyResolver:
    """Resolve issues onto the report's 3 display tiers (0=Epic/1=Story/2=Sub-task).

    Built once per chain; matching is by ``issue_type_id`` first, then by display
    name, mirroring the historical lookup.  An off-chain type resolves to ``None``
    everywhere — callers rely on that to drop excluded issues.
    """

    def __init__(self, chain: list[HierarchyNode]) -> None:
        self._chain = list(chain)
        self._by_id = {n.issue_type_id: n for n in self._chain if n.issue_type_id}
        self._by_name = {n.issue_type: n for n in self._chain if n.issue_type}
        self._by_tier: dict[int, list[HierarchyNode]] = {}
        for n in self._chain:
            self._by_tier.setdefault(n.display_tier, []).append(n)

    def node_of(self, type_id: str, type_name: str = "") -> HierarchyNode | None:
        """The chain node for a type — by id, then by name — or ``None`` if off-chain.

        Accepts the bare ``(id, name)`` form so the customize dialog, which only has
        ``(key, type_id)``, can resolve without a full ``JiraIssue``.  Never returns
        a sentinel for an unknown type: the off-chain drop depends on ``None``.
        """
        return self._by_id.get(type_id) or self._by_name.get(type_name)

    def node_of_issue(self, issue: _Typed) -> HierarchyNode | None:
        """Resolve a ``JiraIssue``-like object to its chain node, or ``None``."""
        return self.node_of(issue.issue_type_id, issue.issue_type)

    def tier_of(self, type_id: str, type_name: str = "") -> int | None:
        """The display tier (0/1/2) for a type, or ``None`` if it is off-chain."""
        node = self.node_of(type_id, type_name)
        return node.display_tier if node is not None else None

    def is_excluded(self, type_id: str, type_name: str = "") -> bool:
        """True when a type is not on the chain (parked in the Exclude pool)."""
        return self.node_of(type_id, type_name) is None

    def nodes_at(self, tier: int) -> list[HierarchyNode]:
        """All chain nodes living at *tier* (a tier may hold several types)."""
        return list(self._by_tier.get(tier, ()))

    def child_nodes_of(self, parent_tier: int) -> list[HierarchyNode]:
        """Chain nodes one tier below *parent_tier* — the direct children's types.

        Each carries its own ``edge``/``link_types`` describing how it attaches, so
        a tier-aware fetch can run the right query per node.
        """
        return self.nodes_at(parent_tier + 1)
