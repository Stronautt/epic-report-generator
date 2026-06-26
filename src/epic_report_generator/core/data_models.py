"""Data models for Epic Report Generator."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Callable, Literal, TypeVar

# Jira status category names — single source of truth across core modules.
STATUS_TODO = "To Do"
STATUS_IN_PROGRESS = "In Progress"
STATUS_DONE = "Done"

# Locale-independent English month names — shared across PDF, chart, and UI code.
MONTHS_ABBR = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]

MONTHS_FULL = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def fmt_date_en(d: date, fmt: str) -> str:
    """Format a date using English month names regardless of system locale.

    Supports ``%B`` (full month) and ``%b`` (abbreviated month); all other
    format codes are delegated to :py:meth:`date.strftime`.
    """
    result = fmt.replace("%B", MONTHS_FULL[d.month - 1])
    result = result.replace("%b", MONTHS_ABBR[d.month - 1])
    return d.strftime(result)


# Scope-certainty vocabulary (FR-13) — ordered low→high for averaging.
CERTAINTY_LEVELS = ["Low", "Medium", "High"]
_CERTAINTY_TO_SCORE = {name: i + 1 for i, name in enumerate(CERTAINTY_LEVELS)}


def average_certainty(values: list[str | None]) -> str | None:
    """Return the rounded average certainty level, or ``None`` when none set.

    Maps ``Low/Medium/High`` to ``1/2/3``, averages the set values, rounds to
    the nearest level, and maps back to a name.  Empty/None inputs are ignored.
    """
    scores = [_CERTAINTY_TO_SCORE[v] for v in values if v in _CERTAINTY_TO_SCORE]
    if not scores:
        return None
    avg = round(sum(scores) / len(scores))
    avg = max(1, min(len(CERTAINTY_LEVELS), avg))
    return CERTAINTY_LEVELS[avg - 1]


_T = TypeVar("_T")


def order_by_keys(
    items: list[_T],
    order: list[str],
    *,
    key: Callable[[_T], str] = lambda x: x,  # type: ignore[assignment,return-value]
) -> list[_T]:
    """Reorder *items* so those whose key is in *order* come first, in that order.

    Items not listed in *order* keep their original relative position, appended
    after (stable). *key* extracts the ordering key from each item (identity for
    a plain key list, ``.key``/``c[0]`` for issues/epics/tuples). An empty
    *order* leaves *items* untouched. Single source of truth for the customize
    dialog's child order and the report's matching order.
    """
    if not order:
        return list(items)
    rank = {k: i for i, k in enumerate(order)}
    fallback = len(rank)
    return sorted(items, key=lambda x: rank.get(key(x), fallback))


@dataclass
class HierarchyNode:
    """One issue type in a report profile's custom hierarchy chain.

    The chain is an ordered list of issue types collapsed into the report's three
    fixed display tiers (0=Epic, 1=Story, 2=Sub-task).  ``edge`` describes how this
    node attaches to the node above it (the first node's edge is ignored): either
    Jira's native ``parent`` relationship or one-or-more issue ``link`` types
    (matched in either direction).  ``show`` is display-only; ``in_estimate``
    controls whether the issue counts in metrics (mirroring the old
    ``include_subtasks``).  An empty :attr:`ReportConfig.issue_hierarchy` derives
    the classic ``Epic→Story→Sub-task`` default.
    """

    issue_type_id: str
    issue_type: str  # display name
    edge: Literal["parent", "link"] = "parent"
    link_types: list[str] = field(default_factory=list)  # names, either direction
    display_tier: int = 0  # 0 = Epic, 1 = Story, 2 = Sub-task
    show: bool = True
    in_estimate: bool = True


def _serialize_node(node: HierarchyNode) -> dict:
    """Serialize a :class:`HierarchyNode` to a compact JSON-able dict.

    Default-valued fields (``parent`` edge, empty links, ``show``/``in_estimate``
    on) are omitted so the stored shape stays minimal, mirroring
    ``_serialize_override``.
    """
    d: dict = {
        "issue_type_id": node.issue_type_id,
        "issue_type": node.issue_type,
        "display_tier": node.display_tier,
    }
    if node.edge != "parent":
        d["edge"] = node.edge
    if node.link_types:
        d["link_types"] = list(node.link_types)
    if not node.show:
        d["show"] = False
    if not node.in_estimate:
        d["in_estimate"] = False
    return d


def serialize_hierarchy(chain: list[HierarchyNode]) -> list[dict]:
    """Serialize a hierarchy chain to a compact JSON-able list."""
    return [_serialize_node(n) for n in chain]


def coerce_hierarchy(raw: list | None) -> list[HierarchyNode]:
    """Normalise persisted/in-memory chain data into ``HierarchyNode`` objects.

    Accepts a list of ``HierarchyNode`` or plain dicts (as stored in config JSON);
    missing fields fall back to defaults (``parent`` edge, shown, estimated).
    """
    result: list[HierarchyNode] = []
    for value in raw or []:
        if isinstance(value, HierarchyNode):
            # ponytail: replace() shallow-copies all scalar fields; only the
            # mutable link_types list needs an explicit copy.
            result.append(replace(value, link_types=list(value.link_types)))
        else:
            value = value or {}
            edge = "link" if value.get("edge") == "link" else "parent"
            result.append(
                HierarchyNode(
                    issue_type_id=str(value.get("issue_type_id", "")),
                    issue_type=str(value.get("issue_type", "")),
                    edge=edge,
                    link_types=list(value.get("link_types") or []),
                    display_tier=int(value.get("display_tier", 0)),
                    show=bool(value.get("show", True)),
                    in_estimate=bool(value.get("in_estimate", True)),
                )
            )
    return result


def epic_tier_type_names(chain: list[HierarchyNode]) -> list[str]:
    """Issue-type names at the Epic display tier (tier 0) of *chain*.

    The single source for the label JQL, label validation, and epic-autocomplete
    scope.  Defaults to ``["Epic"]`` when the chain is empty or carries no tier-0
    type, so it never returns ``[]``.
    """
    names = [n.issue_type for n in chain if n.display_tier == 0 and n.issue_type]
    return names or ["Epic"]


# Classic (name, display_tier) chain used when migrating the removed boolean
# toggles or falling back offline.
_CLASSIC_HIERARCHY: tuple[tuple[str, int], ...] = (
    ("Epic", 0),
    ("Story", 1),
    ("Sub-task", 2),
)


def migrate_default_hierarchy(
    *,
    include_subtasks: bool = True,
    include_subtasks_in_timeline: bool = False,
    show_epic_stories_on_timeline: bool = False,
    show_subtasks_on_timeline: bool = False,
    issue_types: list[dict] | None = None,
) -> list[HierarchyNode]:
    """Derive the classic ``Epic→Story→Sub-task`` chain from the legacy flags.

    Maps the four removed boolean toggles onto per-tier ``show``/``in_estimate``
    so a migrated profile renders identically to the pre-chain behaviour:

    * Sub-task ``in_estimate`` ← ``include_subtasks`` (metrics inclusion).
    * Story ``show`` ← ``show_epic_stories_on_timeline``.
    * Sub-task ``show`` ← ``show_subtasks_on_timeline`` **or**
      ``include_subtasks_in_timeline`` (both surfaced sub-tasks on the timeline;
      either now flips the single ``show`` axis).

    ``issue_types`` (Jira metadata, ``{id, name, ...}``) backfills each node's
    ``issue_type_id`` by exact name when available; offline it stays ``""`` and
    refines on the next Refresh.  Callers leave the chain empty (``[]``) when all
    flags are at their defaults, which derives the same chain implicitly.
    """
    by_name: dict[str, str] = {}
    for t in issue_types or []:
        name = str(t.get("name", ""))
        if name and name not in by_name:
            by_name[name] = str(t.get("id", ""))

    show = {
        0: True,
        1: bool(show_epic_stories_on_timeline),
        2: bool(show_subtasks_on_timeline or include_subtasks_in_timeline),
    }
    estimate = {0: True, 1: True, 2: bool(include_subtasks)}

    return [
        HierarchyNode(
            issue_type_id=by_name.get(name, ""),
            issue_type=name,
            edge="parent",
            display_tier=tier,
            show=show[tier],
            in_estimate=estimate[tier],
        )
        for name, tier in _CLASSIC_HIERARCHY
    ]


# Standard Jira issue types, in the recommended hierarchy. The no-config default
# maps just these onto the three report tiers; any other instance type (custom
# types, other projects' types) is added explicitly in the editor.
_CANONICAL_HIERARCHY: tuple[tuple[str, int], ...] = (
    ("Epic", 0),
    ("Story", 1),
    ("Task", 1),
    ("Bug", 1),
    ("Sub-task", 2),
)
# Accept the hyphen-less spelling some instances use for the sub-task type.
_CANONICAL_NAME_ALIASES: dict[str, set[str]] = {"sub-task": {"sub-task", "subtask"}}


def canonical_default_hierarchy(
    issue_types: list[dict] | None,
) -> list[HierarchyNode]:
    """The recommended Jira default: Epic / Story·Task·Bug / Sub-task only.

    Resolves the five standard Jira issue types against the instance's live types
    (so ids/icons attach) and maps them onto the three report tiers — Epic → Epic,
    Story/Task/Bug → Standard, Sub-task → Sub-task. Every other instance type
    (custom types, other projects' types, cross-project duplicates) is left out of
    the default and must be added in the editor. Show/estimate mirror the classic
    behaviour: only the Epic tier is shown, every tier counts in the metrics.
    Falls back to the classic name-only triple when no metadata is available
    (offline / not yet refreshed).
    """
    if not issue_types:
        return migrate_default_hierarchy(issue_types=issue_types)

    def _id_key(t: dict) -> tuple[int, object]:
        tid = str(t.get("id", ""))
        return (0, int(tid)) if tid.isdigit() else (1, tid)

    def _consistent(t: dict, tier: int) -> bool:
        """Whether *t*'s Jira level matches the tier we want to place it on."""
        level = t.get("hierarchyLevel")
        subtask = bool(t.get("subtask"))
        if tier == 0:
            return isinstance(level, int) and level >= 1
        if tier == 2:
            return subtask or (isinstance(level, int) and level < 0)
        return not subtask and (level is None or level == 0)

    nodes: list[HierarchyNode] = []
    for cname, tier in _CANONICAL_HIERARCHY:
        accepted = _CANONICAL_NAME_ALIASES.get(cname.lower(), {cname.lower()})
        candidates = [
            t
            for t in issue_types
            if str(t.get("name", "")).strip().lower() in accepted
        ]
        if not candidates:
            continue
        # Prefer a type sitting at the expected Jira level, then the lowest id
        # (the canonical/oldest one, so cross-project duplicates collapse to one).
        candidates.sort(key=lambda t: (0 if _consistent(t, tier) else 1, _id_key(t)))
        best = candidates[0]
        nodes.append(
            HierarchyNode(
                issue_type_id=str(best.get("id", "")),
                issue_type=str(best.get("name", "")) or cname,
                edge="parent",
                display_tier=tier,
                show=(tier == 0),
                in_estimate=True,
            )
        )
    return nodes


@dataclass
class SprintInfo:
    """Sprint metadata extracted from a Jira issue's sprint field."""

    name: str
    start_date: date | None = None
    end_date: date | None = None
    state: str = ""


@dataclass
class JiraIssue:
    """A single Jira issue (child of an Epic)."""

    key: str
    summary: str
    status: str
    status_category: str  # "To Do", "In Progress", "Done"
    resolution: str | None
    issue_type: str
    story_points: float | None
    created: datetime | None
    resolved: datetime | None
    assignee: str | None
    parent_key: str | None = None
    start_date: date | None = None
    due_date: date | None = None
    timeline_start: date | None = None
    timeline_end: date | None = None
    sprints: list[SprintInfo] = field(default_factory=list)
    progress: float = 0.0
    effective_weight: float = 1.0
    is_subtask: bool = False
    # Custom-hierarchy fields (set during chain traversal; default-chain leaves them
    # at these benign values so existing 2-tier behaviour is unchanged).
    issue_type_id: str = ""
    hierarchy_parent_key: str | None = None
    display_tier: int = 1  # 0 = Epic, 1 = Story, 2 = Sub-task
    show: bool = True  # display-only
    in_estimate: bool = True  # counts in metrics
    # Changelog-reconstructed history for the trend burnup, populated only for the
    # in-estimate children that feed the chart (and only when the changelog carries
    # the relevant events). Empty → the metrics layer falls back to the
    # created/resolved single-point approximation, byte-for-byte.
    sp_history: list[tuple[datetime, float | None]] = field(default_factory=list)
    done_history: list[tuple[datetime, bool]] = field(default_factory=list)


@dataclass
class EpicData:
    """Full data for a single Jira Epic, including its child issues."""

    key: str
    summary: str
    status: str
    priority: str | None
    assignee: str | None
    reporter: str | None
    created: datetime | None
    updated: datetime | None
    labels: list[str] = field(default_factory=list)
    fix_versions: list[str] = field(default_factory=list)
    children: list[JiraIssue] = field(default_factory=list)
    start_date: date | None = None
    due_date: date | None = None
    timeline_start: date | None = None
    timeline_end: date | None = None


@dataclass
class ChildOverride:
    """Per-child customisation for a report item (FR-13).

    For an epic item the "children" are its stories/tasks; for a label item the
    children are the epics tagged with that label.  Any field may be left at its
    default to leave the corresponding value unchanged.

    ``include`` (default ``True``) controls whether the child is part of the
    report at all — unchecking it drops the child from metrics, the timeline and
    any detail page.  For an *epic* child of a label item the nested
    ``child_overrides`` / ``child_order`` carry that epic's own per-story/task
    customisation (the recursive analogue of :class:`ReportItem`'s fields); they
    stay empty for story/task children, which have no further children.
    """

    display_name: str = ""
    scope_certainty: str | None = None  # None, "Low", "Medium", "High"
    include: bool = True
    child_overrides: dict[str, ChildOverride] = field(default_factory=dict)
    child_order: list[str] = field(default_factory=list)


@dataclass
class ReportItem:
    """A single user input unit for the report — either an epic key or a label."""

    kind: Literal["epic", "label"]
    key: str
    display_name: str = ""
    scope_certainty: str | None = None  # None, "Low", "Medium", "High"
    # Per-child overrides keyed by child Jira key (epic key for label items,
    # story/task key for epic items).  Only used when scope_certainty is unset
    # ("--" / consolidated): the report then shows the average of child values.
    child_overrides: dict[str, ChildOverride] = field(default_factory=dict)
    # User-chosen display order of children (child Jira keys), set by dragging rows
    # in the customize dialog. Drives the order epics appear within a label group and
    # child bars on the timeline. Listed keys are applied first; unlisted children
    # (e.g. newly added in Jira) keep their fetched order. Empty = Jira order.
    child_order: list[str] = field(default_factory=list)


@dataclass
class TimelineItem:
    """Data for a single bar in the timeline Gantt chart."""

    name: str
    start_date: date | None = None
    end_date: date | None = None
    scope_certainty: str | None = None
    progress: float = 0.0
    is_child: bool = False
    group: str = ""
    summary: str = ""
    weight: float = 1.0
    # Custom-hierarchy display: tier (0=epic, 1+=nested child) drives indent and
    # the issue-type icon path drives the boxed icon (empty when not cached).
    display_tier: int = 0
    icon: str = ""


@dataclass
class MilestoneItem:
    """A fix version marker on the timeline chart."""

    name: str
    release_date: date


@dataclass
class EpicMetrics:
    """Calculated metrics for a single Epic."""

    total_issues: int = 0
    completed_issues: int = 0
    open_issues: int = 0
    unestimated_issues: int = 0
    total_sp: float = 0.0
    completed_sp: float = 0.0
    remaining_sp: float = 0.0
    progress: float = 0.0
    avg_cycle_time_days: float | None = None
    velocity_sp_per_week: float | None = None
    scope_change_pct: float | None = None
    blocked_issues: int = 0
    forecast_date: date | None = None
    estimation_unit: str = "SP"
    scope_certainty: str | None = None

    # Time-series data for charts: one entry per changelog event (enter / sp /
    # done), keyed by the event's exact timestamp for the time-proportional axis.
    dates: list[datetime] = field(default_factory=list)
    total_sp_over_time: list[float] = field(default_factory=list)
    completed_sp_over_time: list[float] = field(default_factory=list)
    cumulative_issues: list[int] = field(default_factory=list)
    cumulative_unestimated: list[int] = field(default_factory=list)


@dataclass
class ReportConfig:
    """Configuration for a report generation run."""

    epic_keys: list[str] = field(default_factory=list)
    items: list[ReportItem] = field(default_factory=list)
    title: str = "Epic Progress Report"
    author: str = ""
    project_display_name: str = ""
    report_date: date = field(default_factory=date.today)
    confidential: bool = False
    company_name: str = ""
    estimation_method: str = "story_points"  # "story_points" or "time_days"
    progress_method: str = "combined"  # "combined", "issues_only", or "estimates_only"
    story_points_field: str = "story_points"
    epic_link_field: str = "customfield_10014"
    start_date_field: str = "startdate"
    due_date_field: str = "duedate"
    timeline_start_field: str = "startdate"
    timeline_end_field: str = "duedate"
    timeline_hard_start: date | None = None
    timeline_hard_end: date | None = None
    include_subtasks: bool = True
    include_subtasks_in_timeline: bool = False
    show_epic_stories_on_timeline: bool = False
    show_subtasks_on_timeline: bool = False
    # Custom issue-type hierarchy chain. Empty = derive the classic
    # Epic→Story→Sub-task default (see core.metrics / jira_client).
    issue_hierarchy: list[HierarchyNode] = field(default_factory=list)
    expand_label_details: bool = True
    show_additional_metrics: bool = True
    show_timeline_chart: bool = True  # include/exclude the Gantt timeline page
    dark_mode: bool = False
    # Appearance customization (NFR-05). Empty values keep the stock palette/font.
    report_accent: str = ""  # "" = built-in blue, else "#rrggbb"
    report_font_family: str = ""  # resolved family name; "" = bundled Inter
    report_font_dir: str = ""  # dir of font files for Typst font_paths; "" = none


def collect_child_timeline_dates(
    child: JiraIssue,
    tl_starts: list[date],
    tl_ends: list[date],
) -> None:
    """Append timeline date candidates from a child issue into *tl_starts* / *tl_ends*.

    Cascade order: explicit timeline field → sprint dates → start_date/due_date.
    All eligible sprint dates are appended so callers can take min/max across
    the full set.  This mirrors the Jira Cloud Timeline behaviour which derives
    epic ranges from child sprint assignments when no explicit date fields are set.

    Args:
        child: The child issue whose timeline dates to collect.
        tl_starts: Accumulator list for timeline start date candidates.
        tl_ends: Accumulator list for timeline end date candidates.
    """
    if child.timeline_start:
        tl_starts.append(child.timeline_start)
    else:
        for sp in child.sprints:
            if sp.start_date:
                tl_starts.append(sp.start_date)
        if child.start_date:
            tl_starts.append(child.start_date)

    if child.timeline_end:
        tl_ends.append(child.timeline_end)
    else:
        for sp in child.sprints:
            if sp.end_date:
                tl_ends.append(sp.end_date)
        if child.due_date:
            tl_ends.append(child.due_date)


def collect_child_estimation_dates(
    child: JiraIssue,
    start_dates: list[date],
    end_dates: list[date],
) -> None:
    """Append estimation date candidates from a child issue into the accumulators.

    Cascade: explicit ``start_date`` / ``due_date`` fall back to ``created`` /
    ``resolved`` (``resolved`` only counts when the child is Done), so every
    child contributes a range even without explicit estimation dates.

    Args:
        child: The child issue whose estimation dates to collect.
        start_dates: Accumulator list for start date candidates.
        end_dates: Accumulator list for end (due) date candidates.
    """
    if child.start_date:
        start_dates.append(child.start_date)
    elif child.created:
        start_dates.append(child.created.date())

    if child.due_date:
        end_dates.append(child.due_date)
    elif child.resolved and child.status_category == STATUS_DONE:
        end_dates.append(child.resolved.date())


@dataclass
class ReportData:
    """All data needed to render the final PDF report."""

    config: ReportConfig
    epics: list[EpicData] = field(default_factory=list)
    metrics: list[EpicMetrics] = field(default_factory=list)
    resolved_items: list[tuple[ReportItem, EpicData, EpicMetrics]] = field(
        default_factory=list
    )
    label_source_epics: dict[str, list[tuple[EpicData, EpicMetrics]]] = field(
        default_factory=dict
    )
    fix_version_dates: dict[str, date | None] = field(default_factory=dict)
    sprints: list[SprintInfo] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
