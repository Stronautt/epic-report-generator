#import "../theme.typ": *
#import "../components/pill.typ": certainty-legend
#import "../components/gantt.typ": gantt

// Timeline page: heading + the native Gantt + an optional certainty legend.
// Rendered inside an auto-height page (main.typ). The Gantt has an intrinsic
// height that grows with the number of rows; it is floored so a short timeline
// still fills the standard 16:9 sheet, and taller content grows the page
// instead of paginating.
#let timeline-page(data, c) = {
  let t = data.timeline

  // Neutralise implicit block/paragraph spacing so the floor math below (which
  // measures the heading + legend) matches the rendered flow exactly; every gap
  // is then an explicit v(). Scoped to this page only.
  set block(spacing: 0pt)
  set par(spacing: 0pt)

  layout(size => {
    let head = {
      text(20pt, weight: "bold", fill: c.text)[Timeline]
      v(8pt)
    }
    let legend = if t.has-certainty {
      v(6pt)
      align(right, certainty-legend(c))
    } else { none }

    // Floor the chart so heading + chart + legend exactly fills the standard
    // content height; measuring the fixed parts keeps the fit precise.
    let floor = page-height - 2 * page-margin
    let legend-h = if legend != none { measure(box(width: size.width, legend)).height } else { 0pt }
    let reserved = measure(box(width: size.width, head)).height + legend-h
    let chart-min = calc.max(floor - reserved, 0pt)

    head
    if t.chart != none {
      gantt(t.chart, c, min-height: chart-min)
    } else {
      box(width: 100%, height: chart-min, align(center + horizon, text(fill: c.muted)[No timeline data available]))
    }
    if legend != none { legend }
  })
}
