#import "../theme.typ": *
#import "../components/stat_card.typ": stat-card
#import "../components/pill.typ": pill, status-badge
#import "../components/trend_chart.typ": trend-chart

// Epic detail page: header band, a KPI stat-card row (and an optional
// "Additional" card row), then the trend chart filling the remaining page
// height. Replaces the chart|gap|summary 3-cell table that left the bottom of
// the page empty.
#let epic-page(p, c) = {
  let cards(items) = grid(
    columns: items.len(),
    gutter: 8pt,
    ..items.map(k => stat-card(k.label, k.value, c)),
  )

  let chart-block = block(
    width: 100%,
    height: 100%,
    if p.chart != none {
      trend-chart(p.chart, c)
    } else {
      align(center + horizon, text(fill: c.muted)[No chart data available])
    },
  )

  // Header band: optional label tag, key (accent), optional summary, status badge.
  let header = {
    grid(
      columns: (1fr, auto),
      align: (left + horizon, right + horizon),
      column-gutter: 8pt,
      {
        if p.label-tag != none {
          pill(p.label-tag, c.label-tag-text, c.label-tag-bg)
          h(6pt)
        }
        if p.at("icon", default: "") != "" {
          issue-icon(p.icon, size: 16pt)
          h(6pt)
        }
        text(20pt, weight: "bold", fill: c.accent)[#p.key]
        if p.summary != none {
          text(20pt, fill: c.text)[ · #p.summary]
        }
      },
      status-badge(p.status, c),
    )
    v(5pt)
    line(length: 100%, stroke: 0.75pt + c.grid)
  }

  // Body rows: header, KPI cards, optional additional cards, then 1fr chart.
  let children = (header, cards(p.kpis))
  let rows = (auto, auto)
  if p.additional != none {
    children.push(cards(p.additional))
    rows.push(auto)
  }
  children.push(chart-block)
  rows.push(1fr)

  block(
    width: 100%,
    height: 100%,
    grid(rows: rows, row-gutter: 10pt, ..children),
  )
}
