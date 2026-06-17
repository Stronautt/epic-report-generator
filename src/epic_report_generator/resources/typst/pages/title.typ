// Title page — minimal centered. Vertically centered by the layout engine
// (replaces the 60mm hardcoded ReportLab spacer). No logo, no accent rule.
#let title-page(data, c) = {
  let t = data.title
  block(
    width: 100%,
    height: 100%,
    align(center + horizon, {
      text(34pt, weight: "bold", fill: c.text)[#t.title]
      if t.project != none {
        v(8pt)
        text(18pt, fill: c.muted)[#t.project]
      }
      v(10pt)
      text(16pt, fill: c.muted)[#t.date]
      if t.author != none {
        v(4pt)
        text(14pt, fill: c.muted)[Prepared by #t.author]
      }
    }),
  )
  // Confidential notice pinned to the page bottom.
  if t.notice != none {
    place(
      bottom + center,
      block(width: 80%, align(center, text(9pt, fill: c.red)[#t.notice])),
    )
  }
}
