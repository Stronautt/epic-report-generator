#import "../theme.typ": *
#import "../components/stat_card.typ": stat-card
#import "../components/progress_bar.typ": progress-bar
#import "../components/pill.typ": certainty-dot, certainty-legend

// Summary page: aggregate KPI strip + the epic table (drawn progress bars,
// certainty dots, native group-header rows) + an optional certainty legend.
// Content flows in the normal page region so the table paginates and repeats
// its header when there are many epics.
#let summary-page(data, c) = {
  let s = data.summary

  // Column header cell.
  let h-cell(t) = table.cell(fill: c.accent)[
    #text(fill: c.header-text, weight: "bold", size: 8.5pt)[#t]
  ]

  // One data row -> a tuple of cells. Group rows span Key+Summary and tint the
  // whole row; epic rows fall through to the zebra fill function.
  let row-cells(r) = if r.kind == "group" {
    let lh = c.label-header
    (
      table.cell(colspan: 2, fill: lh)[
        #text(weight: "bold")[#r.label]#h(4pt)#text(7pt, fill: c.muted)[(#r.n-epics epics)]
      ],
      table.cell(fill: lh)[#progress-bar(r.progress, c)],
      table.cell(fill: lh)[#certainty-dot(r.certainty, c)],
      table.cell(fill: lh)[#text(weight: "bold")[#r.status]],
      table.cell(fill: lh)[#text(weight: "bold")[#r.total]],
      table.cell(fill: lh)[#text(weight: "bold")[#r.done]],
      table.cell(fill: lh)[#text(weight: "bold")[#r.unest]],
      table.cell(fill: lh)[#text(weight: "bold")[#r.total-sp]],
      table.cell(fill: lh)[#text(weight: "bold")[#r.done-sp]],
    )
  } else {
    (
      [#text(weight: "medium")[#r.key]], [#r.summary], [#progress-bar(r.progress, c)],
      [#certainty-dot(r.certainty, c)], [#r.status],
      [#r.total], [#r.done], [#r.unest], [#r.total-sp], [#r.done-sp],
    )
  }

  // Whole-page body. Rendered inside an auto-height page (main.typ), so the
  // table never paginates; instead the page grows. A short table is padded up
  // to the standard 16:9 sheet height so small reports look unchanged.
  let body = {
    text(20pt, weight: "bold", fill: c.text)[Epic Progress Summary]
    v(8pt)

    // Aggregate KPI strip.
    grid(columns: s.kpis.len(), gutter: 8pt, ..s.kpis.map(k => stat-card(k.label, k.value, c)))
    v(10pt)

    // Epic table.
    table(
      columns: (auto, 1fr, auto, auto, auto, auto, auto, auto, auto, auto),
      inset: (x: 5pt, y: 4pt),
      align: (left, left, left, center, left, right, right, right, right, right),
      stroke: 0.5pt + c.grid,
      fill: (col, row) => if row > 0 and calc.odd(row) { c.row-alt } else { none },
      table.header(
        h-cell[Key], h-cell[Summary], h-cell[Progress], h-cell[Scope], h-cell[Status],
        h-cell[Total], h-cell[Done], h-cell[Unest.], h-cell[Total #s.unit], h-cell[Done #s.unit],
      ),
      ..s.rows.map(row-cells).flatten()
    )

    if s.has-certainty {
      v(6pt)
      align(right, certainty-legend(c))
    }
  }

  // Pad up to the standard content height (16:9 sheet minus margins) so a short
  // table fills the page; taller content lets the auto-height page grow.
  layout(size => {
    let floor = page-height - 2 * page-margin
    let h = measure(box(width: size.width, body)).height
    body
    if h < floor { v(floor - h) }
  })
}
