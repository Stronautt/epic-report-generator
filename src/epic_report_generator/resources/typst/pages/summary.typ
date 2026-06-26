#import "../theme.typ": *
#import "../components/stat_card.typ": stat-card
#import "../components/progress_bar.typ": progress-bar
#import "../components/pill.typ": certainty-cell, certainty-legend

// Summary page: aggregate KPI strip + the epic table (drawn progress bars,
// certainty dots, native group-header rows) + an optional certainty legend.
// Content flows in the normal page region so the table paginates and repeats
// its header when there are many epics.
#let summary-page(data, c) = {
  let s = data.summary

  // The Scope Certainty column is shown only when at least one item sets it.
  let show-cert = s.has-certainty

  // Column header cell.
  let h-cell(t) = table.cell(fill: c.accent)[
    #text(fill: c.header-text, weight: "bold", size: 8.5pt)[#t]
  ]

  // One data row -> a tuple of cells. Group rows span Key+Summary and tint the
  // whole row; epic rows fall through to the zebra fill function. The certainty
  // cell is spliced in only when the column is shown.
  let row-cells(r) = if r.kind == "group" {
    let lh = c.label-header
    let cert = if show-cert {
      (table.cell(fill: lh)[#certainty-cell(r.certainty, c)],)
    } else { () }
    (
      (
        table.cell(colspan: 2, fill: lh)[
          #text(weight: "bold")[#r.label]#h(4pt)#text(
            7pt,
            fill: c.muted,
          )[(#r.n-epics epics)]
        ],
        table.cell(fill: lh)[#progress-bar(r.progress, c, neutral: show-cert)],
      )
        + cert
        + (
          table.cell(fill: lh)[#text(weight: "bold")[#r.status]],
          table.cell(fill: lh)[#text(weight: "bold")[#r.total]],
          table.cell(fill: lh)[#text(weight: "bold")[#r.done]],
          table.cell(fill: lh)[#text(weight: "bold")[#r.unest]],
          table.cell(fill: lh)[#text(weight: "bold")[#r.total-sp]],
          table.cell(fill: lh)[#text(weight: "bold")[#r.done-sp]],
        )
    )
  } else if r.kind == "child" {
    // Nested chain child (Story/Sub-task tier): indented key + boxed icon, then
    // summary/progress/(cert)/status. The trailing estimate columns stay blank —
    // roll-ups live on the epic row above.
    let cert = if show-cert { ([#certainty-cell(r.certainty, c)],) } else { () }
    let key-cell = {
      h(r.depth * 9pt)
      if r.icon != "" {
        issue-icon(r.icon)
        h(3pt)
      }
      text(8.5pt, fill: c.muted)[#r.key]
    }
    (
      (
        key-cell,
        text(fill: c.muted)[#r.summary],
        progress-bar(r.progress, c, neutral: show-cert),
      )
        + cert
        + (text(fill: c.muted)[#r.status], [], [], [], [], [])
    )
  } else {
    let cert = if show-cert { ([#certainty-cell(r.certainty, c)],) } else { () }
    (
      (
        [#text(weight: "medium")[#r.key]],
        [#r.summary],
        [#progress-bar(r.progress, c, neutral: show-cert)],
      )
        + cert
        + (
          [#r.status],
          [#r.total],
          [#r.done],
          [#r.unest],
          [#r.total-sp],
          [#r.done-sp],
        )
    )
  }

  // Whole-page body. Rendered inside an auto-height page (main.typ), so the
  // table never paginates; instead the page grows. A short table is padded up
  // to the standard 16:9 sheet height so small reports look unchanged.
  let body = {
    text(20pt, weight: "bold", fill: c.text)[Epic Progress Summary]
    v(8pt)

    // Aggregate KPI strip.
    grid(columns: s.kpis.len(), gutter: 8pt, ..s.kpis.map(k => stat-card(
        k.label,
        k.value,
        c,
      )))
    v(10pt)

    // Epic table. Columns, alignment and header all drop the certainty slot
    // together when `show-cert` is false, so the table stays well-formed.
    let cols = (
      (auto, 1fr, auto)
        + (if show-cert { (auto,) } else { () })
        + (auto, auto, auto, auto, auto, auto)
    )
    let aligns = (
      (left, left, left)
        + (if show-cert { (center,) } else { () })
        + (left, right, right, right, right, right)
    )
    let cert-h = if show-cert { (h-cell[Scope Certainty],) } else { () }
    let headers = (
      (h-cell[Key], h-cell[Summary], h-cell[Progress])
        + cert-h
        + (
          h-cell[Status],
          h-cell[Total],
          h-cell[Done],
          h-cell[Unest.],
          h-cell[Total #s.unit],
          h-cell[Done #s.unit],
        )
    )
    table(
      columns: cols,
      inset: (x: 5pt, y: 4pt),
      align: aligns,
      stroke: 0.5pt + c.grid,
      fill: (col, row) => if row > 0 and calc.odd(row) { c.row-alt } else {
        none
      },
      table.header(..headers),
      ..s.rows.map(row-cells).flatten(),
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
