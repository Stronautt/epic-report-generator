#import "../theme.typ": certainty-color, issue-icon, progress-color

// Native Gantt timeline. All geometry is computed from the available region
// (via layout()), so it fills the page and adapts. Stacked top axis (thin):
//
//   [ year/quarter labels ]   <- tier row (thin)
//   [ fix-version pills    ]   <- milestone lane (only when present)
//   [ sprint ribbon        ]   <- contiguous sprint chips (only when present)
//   [ plot: rows + bars    ]
//
// Workstream/label groups become full-width HEADER BANDS (with a progress
// roll-up) interleaved with their rows, so long names fit and never collide
// with the epic keys. `t` is the timeline chart-data dict, `c` the palette.

#let _at(x, y, body) = place(top + left, dx: x, dy: y, body)
#let _ctext(x, y, w, body) = place(top + left, dx: x - w / 2, dy: y, box(
  width: w,
  align(center, body),
))
#let _ltext(x, y, w, body) = place(top + left, dx: x, dy: y, box(
  width: w,
  body,
))
#let _vline(x, y, len, stroke) = place(top + left, dx: x, dy: y, line(
  start: (0pt, 0pt),
  end: (0pt, len),
  stroke: stroke,
))
#let _hline(x, y, len, stroke) = place(top + left, dx: x, dy: y, line(
  start: (0pt, 0pt),
  end: (len, 0pt),
  stroke: stroke,
))

// `color-by-certainty`: when true (any item has a scope certainty) the bars and
// the group roll-up bar are tinted by certainty (the group by its aggregate);
// otherwise both fall back to the progress threshold colour.
#let gantt(t, c, min-height: 0pt, color-by-certainty: false) = layout(sz => {
  let cw = sz.width
  let gutter = 56mm // epic-key column (key + title line, up to ~50 chars)
  let rpad = 15mm // right breathing room for frontier % + Today label
  let botax = 7mm

  let has-sprints = t.sprints.len() > 0
  let has-ms = t.milestones.len() > 0
  let has-sub = t.subtiers.len() > 0
  let tier-h = if has-sub { 6mm } else { 4.5mm }
  let ms-h = if has-ms { 4mm } else { 0mm }
  let sprint-h = if has-sprints { 4.6mm } else { 0mm }
  let topax = tier-h + ms-h + sprint-h + 1mm

  // Interleave group headers with rows. Groups with >= 2 epics get a full band
  // (with a progress roll-up); a trivial 1-epic group gets a compact labelled
  // divider so its lone epic is never mistaken for part of the group above.
  let labelled = t.groups.filter(g => g.label != "")
  let band-h = 5mm
  let div-h = 3.6mm
  let strip-h(g) = if g.n-epics >= 2 { band-h } else { div-h }
  let n = t.rows.len()
  let total-strip = labelled.fold(0mm, (acc, g) => acc + strip-h(g))

  // Intrinsic chart height: a comfortable fixed per-row height so the chart
  // grows with the number of rows, floored to `min-height` so a short timeline
  // still fills the page. Taller content makes the (auto-height) page grow
  // instead of paginating.
  let target-rh = 9mm
  let natural = topax + botax + total-strip + n * target-rh
  let ch = calc.max(natural, min-height)

  let px0 = gutter
  let pw = cw - gutter - rpad
  let py0 = topax
  let ph = ch - topax - botax
  let xof(off) = px0 + pw * (off / t.domain)
  let tx = if t.today != none { xof(t.today) } else { none }

  let body = ph - total-strip
  let rh = if n > 0 { body / n } else { body }
  let header-at(i) = {
    let hit = labelled.filter(g => g.start-row == i)
    if hit.len() > 0 { hit.first() } else { none }
  }
  // top-y of every row band, reserving header/divider space before each group
  let ytops = ()
  let yc0 = py0
  for i in range(n) {
    let hdr = header-at(i)
    if hdr != none { yc0 = yc0 + strip-h(hdr) }
    ytops.push(yc0)
    yc0 = yc0 + rh
  }

  box(width: cw, height: ch, {
    // --- alternating row bands ----------------------------------------------
    for i in range(n) {
      if calc.odd(i) {
        _at(px0, ytops.at(i), rect(
          width: pw,
          height: rh,
          fill: c.surface,
          stroke: none,
        ))
      }
    }

    // --- gridlines + year boundary separators -------------------------------
    // fine (month/week) ticks get faint full-height gridlines; coarse (quarter)
    // ticks do not divide the plot (they become short bottom ticks below).
    if t.tick-grid {
      for tk in t.ticks {
        _vline(xof(tk.off), py0, ph, 0.4pt + c.grid)
      }
    }
    for ti in t.tiers {
      if ti.start > 0 { _vline(xof(ti.start), py0, ph, 0.7pt + c.grid) }
    }

    // --- future region (today -> end) faint shade ---------------------------
    if tx != none and tx < px0 + pw {
      _at(tx, py0, rect(
        width: px0 + pw - tx,
        height: ph,
        fill: c.muted.transparentize(93%),
        stroke: none,
      ))
    }

    _hline(px0, py0, pw, 0.6pt + c.grid)
    _hline(px0, py0 + ph, pw, 0.6pt + c.grid)

    // --- bottom date ticks (suppressed next to Today) -----------------------
    for tk in t.ticks {
      let x = xof(tk.off)
      if not t.tick-grid { _vline(x, py0 + ph, 1.2mm, 0.5pt + c.grid) }
      if tx == none or calc.abs(x - tx) > 7mm {
        _ctext(x, py0 + ph + 1.8mm, 18mm, text(7pt, fill: c.muted)[#tk.label])
      }
    }

    // --- tier band: year labels + quarter sub-dividers ----------------------
    for ti in t.tiers {
      let x0 = xof(ti.start)
      let x1 = xof(ti.end)
      if ti.start > 0 { _vline(x0, 0pt, tier-h, 0.7pt + c.grid) }
      _ctext(x0 + (x1 - x0) / 2, 0.2mm, calc.max(x1 - x0, 14mm), text(
        8.5pt,
        weight: "bold",
        fill: c.muted,
      )[#ti.label])
    }
    for st in t.subtiers {
      let x0 = xof(st.start)
      let x1 = xof(st.end)
      // small quarter divider tick, on the year bar only (never full-height)
      if st.start > 0 { _vline(x0, tier-h - 2.4mm, 2.4mm, 0.6pt + c.grid) }
      // label only when the visible quarter is wide enough to be meaningful
      if x1 - x0 >= 12mm {
        _ctext(x0 + (x1 - x0) / 2, tier-h - 2.7mm, x1 - x0, text(
          6pt,
          fill: c.muted,
        )[#st.label])
      }
    }

    // --- sprint ribbon ------------------------------------------------------
    if has-sprints {
      let sy = tier-h + ms-h
      for (si, s) in t.sprints.enumerate() {
        let x0 = xof(s.start)
        let sw = xof(s.end) - x0
        let fillc = if s.active { c.tl-sprint-active } else if calc.even(si) {
          c.tl-sprint-a
        } else { c.tl-sprint-b }
        let slabel = if sw >= 22mm { s.label } else if sw >= 5mm {
          s.short
        } else { none }
        let content = if slabel != none {
          text(
            5.6pt,
            weight: if s.active { "bold" } else { "regular" },
            fill: c.tl-sprint-text,
          )[#slabel]
        } else { [] }
        // single box with horizon-centred label fixes vertical alignment
        _at(x0, sy + 0.3mm, box(
          width: calc.max(sw - 0.5mm, 0.4mm),
          height: sprint-h - 0.6mm,
          radius: 1pt,
          fill: fillc,
          inset: (x: 1pt, y: 0pt),
          clip: true,
          align(center + horizon, content),
        ))
      }
    }

    // --- group headers: full band (>=2 epics) or compact divider (1 epic) ---
    for g in labelled {
      let sh = strip-h(g)
      let hy = ytops.at(g.start-row) - sh
      let bandc = if g.n-epics >= 2 { c.tl-group-bg } else {
        c.tl-group-bg.transparentize(45%)
      }
      _at(0pt, hy, rect(width: cw, height: sh, fill: bandc, stroke: none))
      _at(0pt, hy, rect(width: 2.2mm, height: sh, fill: c.accent, stroke: none))
      _hline(0pt, hy + sh, cw, 0.5pt + c.tl-group-rule)
      if g.n-epics >= 2 {
        // roll-up (right): mini progress bar + "NN% · N epics"
        let bar-w = 18mm
        let lbl-w = 30mm
        let rx = px0 + pw - bar-w - 2mm - lbl-w
        let pc = if color-by-certainty {
          certainty-color(g.certainty, c)
        } else { progress-color(g.progress, c) }
        _at(rx, hy + sh / 2 - 2pt, rect(
          width: bar-w,
          height: 4pt,
          radius: 2pt,
          fill: c.grid,
          stroke: none,
        ))
        _at(rx, hy + sh / 2 - 2pt, rect(
          width: bar-w * g.progress / 100,
          height: 4pt,
          radius: 2pt,
          fill: pc,
          stroke: none,
        ))
        _ltext(rx + bar-w + 2mm, hy + sh / 2 - 4.5pt, lbl-w, text(
          7pt,
          weight: "bold",
          fill: c.text,
        )[#g.progress% #h(2pt) #text(6.5pt, weight: "regular", fill: c.muted)[#g.n-epics epics]])
        _ltext(3.5mm, hy + sh / 2 - 4pt, rx - 5mm, text(
          7.5pt,
          weight: "bold",
          fill: c.text,
        )[#upper(g.label)])
      } else {
        _ltext(3.5mm, hy + sh / 2 - 3.5pt, pw, text(
          6.5pt,
          weight: "bold",
          fill: c.muted,
        )[#upper(g.label)])
      }
    }

    // --- rows: key (+ title) + bar ------------------------------------------
    for (i, r) in t.rows.enumerate() {
      let yt = ytops.at(i)
      let yc = yt + rh / 2
      let indent = if r.child { 6mm } else { 2mm }
      // Boxed issue-type icon (custom chain only) before the key; reserve a
      // fixed gap so the key never overlaps it. Empty path → no icon, no gap.
      let icon-sz = if r.child { 3.4mm } else { 4mm }
      let icon-gap = if r.icon != "" { icon-sz + 1.4mm } else { 0mm }
      if r.icon != "" {
        _at(indent, yc - icon-sz / 2, issue-icon(r.icon, size: icon-sz))
      }
      let kx = indent + icon-gap
      let keyfs = if r.child { 7pt } else { 8pt }
      let kw = gutter - kx - 2mm
      let show-title = (not r.child) and r.title != "" and rh >= 4.6mm
      if show-title {
        _ltext(kx, yc - 6pt, kw, text(
          keyfs,
          weight: "bold",
          fill: c.text,
        )[#r.key])
        _ltext(kx, yc + 1.5pt, kw, text(5.5pt, fill: c.muted)[#r.title])
      } else {
        _ltext(kx, yc - 4pt, kw, text(
          keyfs,
          weight: if r.child { "regular" } else { "bold" },
          fill: if r.child { c.muted } else { c.text },
        )[#r.key])
      }
      if r.start != none {
        let bx = xof(r.start)
        let bw = xof(r.end) - bx
        let bh = if r.child { calc.min(rh * 0.30, 8pt) } else {
          calc.min(rh * 0.46, 13pt)
        }
        let col = if color-by-certainty {
          certainty-color(r.certainty, c)
        } else { progress-color(r.progress, c) }
        _at(bx, yc - bh / 2, rect(
          width: bw,
          height: bh,
          radius: bh / 2,
          fill: col.transparentize(78%),
          stroke: 0.5pt + col.transparentize(35%),
        ))
        if r.progress > 0 {
          _at(bx, yc - bh / 2, rect(
            width: bw * r.progress / 100,
            height: bh,
            radius: bh / 2,
            fill: col,
            stroke: none,
          ))
        }
        if not r.child {
          let fx = bx + bw * r.progress / 100
          let lbl = text(6.5pt, weight: "bold", fill: c.muted)[#r.progress%]
          if fx + 12mm < px0 + pw + rpad {
            _at(fx + 1.5mm, yc - 4pt, lbl)
          } else {
            _ltext(fx - 12mm, yc - 4pt, 10.5mm, align(right, lbl))
          }
        }
      }
    }

    // --- milestones (fix versions): pill lane + dashed line -----------------
    for m in t.milestones {
      let x = xof(m.off)
      _vline(x, tier-h + ms-h, ph + (py0 - tier-h - ms-h), (
        paint: c.yellow,
        thickness: 1pt,
        dash: "dashed",
      ))
      _ctext(x, tier-h + 0.3mm, 30mm, box(
        inset: (x: 4pt, y: 1pt),
        radius: 3pt,
        fill: c.yellow.transparentize(55%),
        stroke: 0.5pt + c.yellow,
      )[#text(6.5pt, weight: "bold", fill: c.text)[#m.label]])
    }

    // --- today marker -------------------------------------------------------
    if tx != none {
      _vline(tx, py0, ph, (
        paint: c.accent,
        thickness: 1pt,
        dash: "densely-dotted",
      ))
      _ctext(tx, py0 + ph + 3.4mm, 16mm, text(
        6.5pt,
        weight: "bold",
        fill: c.accent,
      )[Today])
    }
  })
})
