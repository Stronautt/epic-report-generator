#import "../theme.typ": certainty-color

// A filled rounded label — used for the status badge and the label tag.
#let pill(label, fg, bg) = box(
  inset: (x: 6pt, y: 2pt),
  radius: 6pt,
  fill: bg,
)[#text(8.5pt, weight: "medium", fill: fg)[#label]]

// Status badge, coloured by status category. In-progress uses a fixed blue
// (`info`) rather than the accent, so a custom accent never recolours it.
#let status-badge(status, c) = {
  let col = if status == "Done" { c.green } else if status == "To Do" { c.muted } else { c.info }
  pill(status, white, col)
}

// Coloured dot + label for a scope-certainty cell ("--" when unknown).
#let certainty-dot(s, c) = {
  if s == none {
    text(fill: c.muted)[--]
  } else {
    box(baseline: 20%, circle(radius: 2.5pt, fill: certainty-color(s, c), stroke: none))
    h(3pt)
    text(8pt, weight: "medium")[#s]
  }
}

// Inline High / Medium / Low certainty legend.
#let certainty-legend(c) = {
  let item(s) = {
    box(baseline: 20%, circle(radius: 2.5pt, fill: certainty-color(s, c), stroke: none))
    h(2pt)
    s
  }
  text(8pt, fill: c.muted)[
    Scope Certainty:#h(6pt)#item("High")#h(10pt)#item("Medium")#h(10pt)#item("Low")
  ]
}
