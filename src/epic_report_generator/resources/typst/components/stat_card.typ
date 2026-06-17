// A KPI card: a muted upper-case label over a bold value, in a rounded surface
// box. Used for the summary KPI strip and the per-epic metric cards. Replaces
// the cramped right-hand metrics table faked with ReportLab.
#let stat-card(label, value, c) = box(
  width: 100%,
  inset: (x: 9pt, y: 7pt),
  radius: 5pt,
  fill: c.surface,
  stroke: 0.5pt + c.grid,
)[
  #text(7.5pt, fill: c.muted)[#upper(label)]
  #v(3pt, weak: true)
  #text(15pt, weight: "bold", fill: c.text)[#value]
]
