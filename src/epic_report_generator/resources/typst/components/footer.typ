// Confidential footer, rendered on every page except the title page (page 1).
// Native page footer — replaces the ReportLab onPage canvas callback and the
// mutable page_counter closure.
#let make-footer(data, c) = context {
  let f = data.footer
  if f.enabled and here().page() > 1 {
    set text(7pt)
    grid(
      columns: (1fr, 1fr),
      align(left)[#text(fill: c.red, weight: "bold")[CONFIDENTIAL — #f.company]],
      align(right)[#text(fill: c.muted)[#f.right]],
    )
  }
}
