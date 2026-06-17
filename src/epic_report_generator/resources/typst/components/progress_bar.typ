#import "../theme.typ": progress-color

// A drawn progress bar: a rounded track with a filled portion coloured by
// threshold, followed by the "NN %" label. Replaces the Unicode ■/□ glyph hack.
#let progress-bar(pct, c, width: 26mm) = {
  let p = calc.max(0, calc.min(100, pct))
  box(
    baseline: 25%,
    width: width,
    height: 7pt,
    radius: 3.5pt,
    fill: c.grid,
  )[
    #place(
      left + horizon,
      box(width: p / 100 * 100%, height: 7pt, radius: 3.5pt, fill: progress-color(p, c)),
    )
  ]
  h(4pt)
  text(8pt, weight: "bold")[#calc.round(p) %]
}
