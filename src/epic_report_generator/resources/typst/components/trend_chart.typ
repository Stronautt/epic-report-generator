// Native dual-axis trend chart: story-point areas (total + completed) on the
// left axis, cumulative issue + unestimated lines on the right axis. All
// geometry is computed from the available region (layout()), so it fills the
// page region and stays crisp. Replaces the matplotlib trend image.
//
// `d` is the trend chart-data dict, `c` the theme palette.

#let _at(x, y, body) = place(top + left, dx: x, dy: y, body)
#let _ctext(x, y, w, body) = place(top + left, dx: x - w / 2, dy: y, box(width: w, align(center, body)))
#let _hline(x, y, len, stroke) = place(top + left, dx: x, dy: y, line(start: (0pt, 0pt), end: (len, 0pt), stroke: stroke))
#let _polyline(pts, stroke) = place(top + left, curve(stroke: stroke,
  curve.move(pts.at(0)), ..pts.slice(1).map(p => curve.line(p))))

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
  let xof(i) = px0 + pw * (i / (n - 1))
  let ysp(v) = py0 + ph * (1 - v / d.sp-max)
  let yiss(v) = py0 + ph * (1 - v / d.iss-max)
  let ybase = py0 + ph

  let total-fill = c.muted.transparentize(82%)
  let done-fill = c.accent.transparentize(58%)
  let iss-line = c.accent
  let unest-line = c.yellow

  box(width: cw, height: ch, {
    // horizontal gridlines + left (SP) axis labels
    for tk in d.sp-ticks {
      let y = ysp(tk)
      _hline(px0, y, pw, 0.4pt + c.grid)
      place(top + left, dx: 0pt, dy: y - 4pt, box(width: gl - 2mm, align(right, text(7pt, fill: c.muted)[#tk])))
    }
    // right (issues) axis labels
    for tk in d.iss-ticks {
      place(top + left, dx: px0 + pw + 2mm, dy: yiss(tk) - 4pt, text(7pt, fill: c.muted)[#tk])
    }

    // areas: total then completed on top
    let area(vals, fill) = {
      let pts = range(n).map(i => (xof(i), ysp(vals.at(i))))
      pts = pts + ((xof(n - 1), ybase), (xof(0), ybase))
      place(top + left, polygon(fill: fill, stroke: none, ..pts))
    }
    area(d.total-sp, total-fill)
    area(d.done-sp, done-fill)

    // right-axis lines
    _polyline(range(n).map(i => (xof(i), yiss(d.cum-iss.at(i)))), 1.6pt + iss-line)
    _polyline(range(n).map(i => (xof(i), yiss(d.cum-unest.at(i)))),
      (paint: unest-line, thickness: 1.4pt, dash: "dashed"))

    // x baseline + tick labels
    _hline(px0, ybase, pw, 0.6pt + c.grid)
    for tk in d.x-ticks {
      _ctext(xof(tk.i), ybase + 2mm, 18mm, text(7pt, fill: c.muted)[#tk.label])
    }

    // axis titles
    place(top + left, dx: 0pt, dy: py0 - 6mm, text(7pt, weight: "bold", fill: c.muted)[SP])
    place(top + left, dx: px0 + pw + 1mm, dy: py0 - 6mm, text(7pt, weight: "bold", fill: c.muted)[Issues])

    // legend
    let sw(col, label, dashed: false) = box(baseline: 25%)[
      #box(width: 10pt, height: 7pt, fill: if dashed { none } else { col },
        stroke: if dashed { (paint: col, thickness: 1.2pt, dash: "dashed") } else { none })
      #h(3pt) #text(7pt, fill: c.muted)[#label]
    ]
    place(top + center, dy: 0pt)[
      #sw(total-fill, "Total " + d.unit) #h(8pt) #sw(done-fill, "Completed " + d.unit) #h(8pt)
      #sw(iss-line, "Cumulative Issues") #h(8pt) #sw(unest-line, "Unestimated", dashed: true)
    ]
  })
})
