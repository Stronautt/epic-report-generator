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
  let col = if status == "Done" { c.green } else if status == "To Do" {
    c.muted
  } else { c.info }
  pill(status, white, col)
}

// Number of filled segments for a certainty level (High=3, Medium=2, Low=1).
#let _cert-level(s) = if s == "High" { 3 } else if s == "Medium" { 2 } else if (
  s == "Low"
) { 1 } else { 0 }

// A 3-segment confidence meter: the leading `level` segments are tinted by the
// certainty colour, the rest stay muted. The discrete segmented shape reads
// nothing like the (neutral, continuous) progress bar, so colour reliably means
// certainty and bar length means progress.
#let cert-meter(s, c) = {
  let n = _cert-level(s)
  let col = certainty-color(s, c)
  box(baseline: 15%, {
    for i in range(3) {
      if i > 0 { h(1.6pt) }
      box(width: 3.2pt, height: 8pt, radius: 1pt, fill: if i < n { col } else {
        c.grid
      })
    }
  })
}

// Scope-certainty cell: the meter + word label ("--" when unknown).
#let certainty-cell(s, c) = {
  if s == none {
    text(fill: c.muted)[--]
  } else {
    cert-meter(s, c)
    h(4pt)
    text(8pt, weight: "medium")[#s]
  }
}

// Inline High / Medium / Low certainty legend, using the same meter glyph.
#let certainty-legend(c) = {
  let item(s) = {
    cert-meter(s, c)
    h(3pt)
    s
  }
  text(8pt, fill: c.muted)[
    Scope Certainty:#h(6pt)#item("High")#h(10pt)#item("Medium")#h(10pt)#item("Low")
  ]
}
