// Entry point for the Epic progress report. Loads the JSON view-model written
// next to this file by the Python renderer and emits the pages in order:
// title -> summary -> (optional) timeline -> one page per epic.
#import "theme.typ": pal, page-width, page-height, page-margin
#import "components/footer.typ": make-footer
#import "pages/title.typ": title-page
#import "pages/summary.typ": summary-page
#import "pages/timeline.typ": timeline-page
#import "pages/epic.typ": epic-page

#let data = json("data.json")
#let c = pal(data.theme.dark)

// Appearance customization (NFR-05): merge accent-family colour overrides over
// the base palette, then pick the custom report font (bundled Inter fallback).
#let color-overrides = data.theme.at("colors", default: (:))
#for (name, hex) in color-overrides { c.insert(name, rgb(hex)) }
#let font-name = data.theme.at("font", default: "")
#let body-font = if font-name != "" { (font-name, "Inter") } else { ("Inter",) }

#set document(
  title: data.title.title,
  author: if data.title.author != none { data.title.author } else { "" },
)
#set text(font: body-font, size: 11pt, fill: c.text)
#set page(
  width: page-width,
  height: page-height,
  margin: page-margin,
  fill: c.bg,
  footer: make-footer(data, c),
)

#title-page(data, c)

// Summary and timeline live on their own auto-height pages: when the table or
// the Gantt is taller than the standard sheet, the page grows instead of
// paginating (the floor stays the 16:9 height — see summary.typ/timeline.typ).
#page(height: auto)[
  #summary-page(data, c)
]

#if data.timeline.enabled {
  page(height: auto)[
    #timeline-page(data, c)
  ]
}

#for pg in data.pages {
  pagebreak(weak: true)
  epic-page(pg, c)
}
