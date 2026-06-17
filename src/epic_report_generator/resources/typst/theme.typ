// Theme: colour palettes (light/dark), thresholds, geometry, and shared helpers.
// Single source of truth for report styling — replaces the two Python palette
// dicts and the `_hex()` juggling in the old ReportLab generator.

#let palettes = (
  light: (
    accent: rgb("#0052CC"),
    text: rgb("#172B4D"),
    muted: rgb("#6B778C"),
    bg: white,
    surface: rgb("#F4F5F7"),
    green: rgb("#36B37E"),
    yellow: rgb("#FFAB00"),
    red: rgb("#DE350B"),
    info: rgb("#0052CC"),  // in-progress status — fixed blue, independent of accent
    row-alt: rgb("#F8F9FA"),
    grid: rgb("#DFE1E6"),
    header-text: white,
    label-header: rgb("#E8EDFC"),
    label-tag-bg: rgb("#DEEBFF"),
    label-tag-text: rgb("#0747A6"),
    // timeline-specific
    tl-group-bg: rgb("#EAEFFA"),
    tl-group-rule: rgb("#C9D6EE"),
    tl-sprint-a: rgb("#EFEDFB"),
    tl-sprint-b: rgb("#E4E0F6"),
    tl-sprint-active: rgb("#C9BEF0"),
    tl-sprint-text: rgb("#5243AA"),
    tl-sprint-line: rgb("#E9E4F7"),
    tl-future: rgb("#F6F7F9"),
  ),
  dark: (
    accent: rgb("#2979FF"),
    text: rgb("#E0E0E0"),
    muted: rgb("#90A4AE"),
    bg: rgb("#1E1E1E"),
    surface: rgb("#263238"),
    green: rgb("#66BB6A"),
    yellow: rgb("#FFA726"),
    red: rgb("#EF5350"),
    info: rgb("#2979FF"),  // in-progress status — fixed blue, independent of accent
    row-alt: rgb("#252525"),
    grid: rgb("#37474F"),
    header-text: white,
    label-header: rgb("#1A3352"),
    label-tag-bg: rgb("#0D2137"),
    label-tag-text: rgb("#82B1FF"),
    // timeline-specific
    tl-group-bg: rgb("#243449"),
    tl-group-rule: rgb("#3A4D66"),
    tl-sprint-a: rgb("#2A2540"),
    tl-sprint-b: rgb("#332C4D"),
    tl-sprint-active: rgb("#4A3F70"),
    tl-sprint-text: rgb("#C7B6E8"),
    tl-sprint-line: rgb("#2F2A42"),
    tl-future: rgb("#212327"),
  ),
)

// Return the active palette for the given dark-mode flag.
#let pal(dark) = if dark { palettes.dark } else { palettes.light }

// Progress thresholds (percent): green >= 75, yellow >= 25, red below.
#let progress-high = 75
#let progress-low = 25
#let progress-color(pct, c) = {
  if pct >= progress-high { c.green } else if pct >= progress-low { c.yellow } else { c.red }
}

// Scope-certainty colour mapping.
#let certainty-color(s, c) = {
  if s == "High" { c.green } else if s == "Medium" { c.yellow } else if s == "Low" { c.red } else { c.muted }
}

// Page geometry — landscape 16:9.
#let page-width = 406mm
#let page-height = 228.4mm
#let page-margin = 18mm
