// Native dual-axis trend chart: story-point areas (total + completed) on the
// left axis, cumulative issue + unestimated lines on the right axis. All
// geometry is computed from the available region (layout()), so it fills the
// page region and stays crisp. Replaces the matplotlib trend image.
//
// `d` is the trend chart-data dict, `c` the theme palette.

#let _at(x, y, body) = place(top + left, dx: x, dy: y, body)
#let _ctext(x, y, w, body) = place(top + left, dx: x - w / 2, dy: y, box(
  width: w,
  align(center, body),
))
#let _hline(x, y, len, stroke) = place(top + left, dx: x, dy: y, line(
  start: (0pt, 0pt),
  end: (len, 0pt),
  stroke: stroke,
))
#let _polyline(pts, stroke) = place(top + left, curve(
  stroke: stroke,
  curve.move(pts.at(0)),
  ..pts.slice(1).map(p => curve.line(p)),
))

#let _fs = 7pt  // chart label font size used throughout
#let trend-chart(d, c) = layout(sz => {
  let cw = sz.width
  let ch = sz.height
  let gl = 13mm
  let gr = 13mm
  let topax = 9mm
  let botax = 8mm
  let px0 = gl
  let pw = cw - gl - gr
  let py0 = topax
  let ph = ch - topax - botax
  let n = d.n
  // Time-proportional x: each point carries its own fraction of the span (xs),
  // so same-day events spread apart like Jira's burnup instead of sitting on a
  // uniform index grid.
  let xof(i) = px0 + pw * d.xs.at(i)
  let ysp(v) = py0 + ph * (1 - v / d.sp-max)
  let yiss(v) = py0 + ph * (1 - v / d.iss-max)
  let ybase = py0 + ph

  // Step-after interpolation (staircase, like Jira): a cumulative value holds
  // flat from its sample until the next, then jumps — never a diagonal ramp.
  let step-pts(vals, yf) = {
    let pts = ()
    for i in range(n) {
      if i > 0 { pts.push((xof(i), yf(vals.at(i - 1)))) }
      pts.push((xof(i), yf(vals.at(i))))
    }
    pts
  }

  let total-fill = c.muted.transparentize(82%)
  let done-fill = c.accent.transparentize(58%)
  let iss-line = c.accent
  // Unestimated uses a neutral, accent-independent, mode-adaptive ink (not the
  // amber `c.yellow`): the Completed-SP area is tinted by the report accent, so a
  // warm accent (orange/amber) hid an amber line on it. `c.text` stays legible on
  // both the grey Total-SP area and the accent-tinted Completed-SP area, in light
  // and dark, for any accent — a fixed hue can't (it would collide when the accent
  // happens to share it).
  let unest-line = c.text

  box(width: cw, height: ch, {
    // alternating weekly background bands (calendar structure, like Jira) —
    // drawn first so gridlines, areas and lines sit on top.
    for b in d.at("bands", default: ()) {
      place(top + left, dx: px0 + pw * b.x0, dy: py0, rect(
        width: pw * (b.x1 - b.x0),
        height: ph,
        fill: c.surface,
        stroke: none,
      ))
    }
    // horizontal gridlines + left (SP) axis labels
    for tk in d.sp-ticks {
      let y = ysp(tk)
      _hline(px0, y, pw, 0.4pt + c.grid)
      place(top + left, dx: 0pt, dy: y - 4pt, box(width: gl - 2mm, align(
        right,
        text(_fs, fill: c.muted)[#tk],
      )))
    }
    // right (issues) axis labels
    for tk in d.iss-ticks {
      place(top + left, dx: px0 + pw + 2mm, dy: yiss(tk) - 4pt, text(
        _fs,
        fill: c.muted,
      )[#tk])
    }

    // areas: total then completed on top (stepped top edge)
    let area(vals, fill) = {
      let pts = step-pts(vals, ysp) + ((xof(n - 1), ybase), (xof(0), ybase))
      place(top + left, polygon(fill: fill, stroke: none, ..pts))
    }
    area(d.total-sp, total-fill)
    area(d.done-sp, done-fill)

    // right-axis lines (stepped)
    _polyline(step-pts(d.cum-iss, yiss), 1.6pt + iss-line)
    _polyline(step-pts(d.cum-unest, yiss), (
      paint: unest-line,
      thickness: 1.4pt,
      dash: "dashed",
    ))

    // x baseline + tick labels
    _hline(px0, ybase, pw, 0.6pt + c.grid)
    for tk in d.x-ticks {
      _ctext(
        px0 + pw * tk.x,
        ybase + 2mm,
        18mm,
        text(_fs, fill: c.muted)[#tk.label],
      )
    }

    // axis titles
    place(top + left, dx: 0pt, dy: py0 - 6mm, text(
      _fs,
      weight: "bold",
      fill: c.muted,
    )[SP])
    place(top + left, dx: px0 + pw + 1mm, dy: py0 - 6mm, text(
      _fs,
      weight: "bold",
      fill: c.muted,
    )[Issues])

    // legend
    let sw(col, label, dashed: false) = box(baseline: 25%)[
      #box(
        width: 10pt,
        height: _fs,
        fill: if dashed { none } else { col },
        stroke: if dashed {
          (paint: col, thickness: 1.2pt, dash: "dashed")
        } else { none },
      )
      #h(3pt) #text(_fs, fill: c.muted)[#label]
    ]
    place(top + center, dy: 0pt)[
      #sw(total-fill, "Total " + d.unit) #h(8pt) #sw(
        done-fill,
        "Completed " + d.unit,
      ) #h(8pt)
      #sw(iss-line, "Cumulative Issues") #h(8pt) #sw(
        unest-line,
        "Unestimated",
        dashed: true,
      )
    ]
  })
})
