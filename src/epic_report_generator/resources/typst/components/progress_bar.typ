#import "../theme.typ": progress-color

// A drawn progress bar: a rounded track with a filled portion, followed by the
// "NN %" label. When `neutral` is true the fill is a neutral grey — *length*
// alone encodes percent, freeing *colour* for the scope-certainty meter so the
// two columns never share a colour language. When false the bar reclaims the
// informative threshold colour (used when no certainty column is shown, so
// there is no collision to avoid).
#let progress-bar(pct, c, neutral: true, width: 26mm) = {
  let p = calc.max(0, calc.min(100, pct))
  let fill = if neutral { c.muted } else { progress-color(p, c) }
  box(
    baseline: 25%,
    width: width,
    height: 7pt,
    radius: 3.5pt,
    fill: c.grid,
  )[
    #place(
      left + horizon,
      box(width: p / 100 * 100%, height: 7pt, radius: 3.5pt, fill: fill),
    )
  ]
  h(4pt)
  text(8pt, weight: "bold")[#calc.round(p) %]
}
