/* Shared by every page of the site; inlined by scripts/build_site.py. */
"use strict";

const DATA = JSON.parse(document.getElementById("budget-data").textContent);
const YEARS = DATA.years;
const ITEMS = new Map(DATA.items.map((it) => [it.id, it]));
const SVG_NS = "http://www.w3.org/2000/svg";
const MINUS = "−";
// The borough's figures are rounded to the dollar, so the same total can be
// printed a few dollars apart in two documents. Only larger differences are
// flagged as revisions.
const ROUNDING = 5;

// ---------------------------------------------------------------- URL state
// Page settings live in the URL fragment so views can be shared and the
// dollars setting carries between pages.

function readParams() { return new URLSearchParams(location.hash.slice(1)); }
function writeParams(params) {
  const hash = "#" + new URLSearchParams(params).toString();
  if (location.hash !== hash) history.replaceState(null, "", hash);
  document.querySelectorAll("a[data-keep-dollars]").forEach((a) => {
    a.href = a.getAttribute("href").split("#")[0] + "#dollars=" + DOLLARS.mode;
  });
}

// ---------------------------------------------------------------- dollars
// "nominal": as printed in the budgets. "real": adjusted for inflation with
// the Consumer Price Index (CPI-U), expressed in the latest year's dollars.

const DOLLARS = { mode: "nominal" };
const CPI = DATA.cpi;
function hasCpi() { return !!(CPI && CPI.index); }
function factor(year) {
  if (DOLLARS.mode !== "real" || !hasCpi()) return 1;
  return CPI.index[CPI.ref_year] / CPI.index[year];
}
function adjust(v, year) { return v === null || v === undefined ? null : v * factor(year); }
function dollarsPhrase() {
  return DOLLARS.mode === "real" && hasCpi()
    ? `in ${CPI.ref_year} dollars (adjusted for inflation)`
    : "in dollars (not adjusted for inflation)";
}

// ---------------------------------------------------------------- formatting

function money(v) {
  return (v < 0 ? MINUS : "") + "$" + Math.abs(Math.round(v)).toLocaleString("en-US");
}
function trimNum(x) { return String(+x.toFixed(2)); }
function moneyCompact(v) {
  const a = Math.abs(v), s = v < 0 ? MINUS : "";
  if (a >= 1e6) return s + "$" + trimNum(a / 1e6) + "M";
  if (a >= 1e5) return s + "$" + Math.round(a / 1e3) + "K";
  if (a >= 1e4) return s + "$" + (+(a / 1e3).toFixed(1)) + "K";
  return s + "$" + Math.round(a).toLocaleString("en-US");
}
function signedMoney(v, compact) {
  const f = compact ? moneyCompact : money;
  return v > 0 ? "+" + f(v) : f(v);
}
function pct(v, digits = 1) {
  if (v === null || !isFinite(v)) return "n/a";
  const s = v > 0 ? "+" : v < 0 ? MINUS : "";
  return s + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }) + "%";
}
function pctChange(cur, base) {
  return cur !== null && base !== null && base > 0 ? ((cur - base) / base) * 100 : null;
}
function annualRate(first, last, years) {
  return first > 0 && last > 0 && years > 0 ? (Math.pow(last / first, 1 / years) - 1) * 100 : null;
}
function docLabel(docId) { return DATA.docs[docId].title; }
function sourceUrl(docId, page) { return DATA.docs[docId].url + "#page=" + page; }
function explorerUrl(itemId) { return `explorer.html#item=${encodeURIComponent(itemId)}&dollars=${DOLLARS.mode}`; }

// ---------------------------------------------------------------- data access

// The figure for one budget line, year and measure ("a" adopted budget,
// "e" estimated actual, "r" restated budget), in the current dollars mode.
function value(id, year, measure = "a") {
  const r = (DATA.values[id] || {})[year];
  return r && r[measure] !== undefined ? adjust(r[measure], year) : null;
}

// Everything about one budget line, year by year.
function seriesFor(id) {
  const v = DATA.values[id] || {};
  return YEARS.map((y) => {
    const r = v[y] || {};
    return {
      year: y,
      adopted: adjust(r.a, y), adoptedNominal: r.a ?? null, aDoc: r.ad, aPage: r.ap, aCorrected: !!r.ac, aError: r.as || "",
      estimate: adjust(r.e, y), estimateNominal: r.e ?? null, eDoc: r.ed, ePage: r.ep, eCorrected: !!r.ec, eError: r.es || "",
      restated: r.r ?? null, rDoc: r.rd, rPage: r.rp, rError: r.rs || "",
    };
  });
}
function revised(d) {
  return d.restated !== null && d.adoptedNominal !== null && Math.abs(d.restated - d.adoptedNominal) > ROUNDING;
}

// ---------------------------------------------------------------- page bits

function setupSegmented(id, get, set) {
  const box = document.getElementById(id);
  const sync = () => box.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.value === get())));
  box.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b || b.disabled) return;
    set(b.dataset.value);
    sync();
  });
  sync();
  return sync;
}

function addTile(container, label, valueText, delta, title) {
  const t = document.createElement("div");
  t.className = "tile";
  const l = document.createElement("div"); l.className = "label"; l.textContent = label;
  const v = document.createElement("div"); v.className = "value"; v.textContent = valueText;
  if (title) v.title = title;
  t.append(l, v);
  if (delta) { const d = document.createElement("div"); d.className = "delta"; d.textContent = delta; t.append(d); }
  container.appendChild(t);
}

// ---------------------------------------------------------------- charts

function niceTicks(lo, hi, count = 5) {
  if (lo === hi) { hi = lo === 0 ? 1 : lo * 1.1; lo = Math.min(0, lo); }
  const raw = (hi - lo) / count;
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  const f = raw / p;
  const step = (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
  const nlo = Math.floor(lo / step) * step, nhi = Math.ceil(hi / step) * step;
  const ticks = [];
  for (let v = nlo; v <= nhi + step / 2; v += step) ticks.push(+v.toFixed(10));
  return { lo: nlo, hi: nhi, ticks };
}

function moneyTicks(values) {
  const ticks = niceTicks(Math.min(0, ...values), Math.max(0, ...values));
  const compact = Math.max(Math.abs(ticks.lo), Math.abs(ticks.hi)) >= 1e4;
  return { ticks, format: (t) => (compact ? moneyCompact(t) : money(t)) };
}

function el(tag, attrs = {}, parent) {
  const e = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
}

// An SVG plot with a y axis, gridlines and year labels along the bottom.
// `band`: years are columns (bar charts) rather than points (line charts).
function frame(fig, { height, labels, yTicks, tickFormat, band = false, margin = {} }) {
  const plot = fig.querySelector(".plot");
  plot.textContent = "";
  const width = Math.max(300, plot.clientWidth);
  const m = { t: 16, r: 64, b: 28, l: 64, ...margin };
  const svg = el("svg", { width, height, viewBox: `0 0 ${width} ${height}`, tabindex: 0 }, plot);
  const n = labels.length;
  const step = band ? (width - m.l - m.r) / n : (width - m.l - m.r) / Math.max(1, n - 1);
  const x = (i) => (band ? m.l + step * (i + 0.5) : m.l + i * step);
  const y = (v) => m.t + ((yTicks.hi - v) * (height - m.t - m.b)) / (yTicks.hi - yTicks.lo || 1);
  for (const t of yTicks.ticks) {
    el("line", { x1: m.l, x2: width - m.r + (band ? 0 : 8), y1: y(t), y2: y(t), stroke: t === 0 ? "var(--axis)" : "var(--grid)", "stroke-width": 1 }, svg);
    const label = el("text", { x: m.l - 8, y: y(t) + 4, "text-anchor": "end" }, svg);
    label.textContent = tickFormat(t);
  }
  const every = step < 44 ? 2 : 1;
  labels.forEach((lab, i) => {
    if ((n - 1 - i) % every) return;  // always label the latest year
    const t = el("text", { x: x(i), y: height - 8, "text-anchor": "middle" }, svg);
    t.textContent = String(lab);
  });
  return { svg, width, height, m, x, y, step, n };
}

// Hover and keyboard reading of a chart: snaps to the nearest year (or
// column), optionally drawing a crosshair, and fills the tooltip via `show`.
function interact(fig, f, show, { crosshair = true, onLeave } = {}) {
  const tip = fig.querySelector(".tooltip");
  const cross = crosshair
    ? el("line", { y1: f.m.t, y2: f.height - f.m.b, stroke: "var(--muted)", "stroke-width": 1, visibility: "hidden" }, f.svg)
    : null;
  const hit = el("rect", { x: f.m.l - 16, y: 0, width: f.width - f.m.l - f.m.r + 32, height: f.height, fill: "transparent" }, f.svg);
  let current = f.n - 1;
  function at(i) {
    current = Math.max(0, Math.min(f.n - 1, i));
    if (cross) {
      cross.setAttribute("x1", f.x(current));
      cross.setAttribute("x2", f.x(current));
      cross.setAttribute("visibility", "visible");
    }
    tip.textContent = "";
    show(current, tip);
    tip.hidden = false;
    const xPos = f.x(current);
    const left = xPos + 16 + tip.offsetWidth > f.width ? xPos - 16 - tip.offsetWidth : xPos + 16;
    tip.style.left = Math.max(0, left) + "px";
    tip.style.top = f.m.t + 4 + "px";
  }
  function hide() {
    tip.hidden = true;
    if (cross) cross.setAttribute("visibility", "hidden");
    if (onLeave) onLeave();
  }
  hit.addEventListener("pointermove", (e) => {
    const px = e.clientX - f.svg.getBoundingClientRect().left - f.m.l;
    at(f.step ? Math.floor(px / f.step + (f.x(0) === f.m.l ? 0.5 : 0)) : 0);
  });
  hit.addEventListener("pointerleave", hide);
  f.svg.addEventListener("focus", () => at(current));
  f.svg.addEventListener("blur", hide);
  f.svg.addEventListener("keydown", (e) => {
    if (e.key === "ArrowLeft") { at(current - 1); e.preventDefault(); }
    if (e.key === "ArrowRight") { at(current + 1); e.preventDefault(); }
  });
}

function tipRow(tip, color, valueText, name, cls = "") {
  const row = document.createElement("div");
  row.className = "tt-row " + cls;
  const key = document.createElement("span");
  key.className = "key";
  key.style.background = color;
  const strong = document.createElement("strong");
  strong.textContent = valueText;
  const label = document.createElement("span");
  label.className = "name";
  label.textContent = name;
  row.append(key, strong, label);
  tip.appendChild(row);
}
function tipText(tip, cls, text) {
  const d = document.createElement("div");
  d.className = cls;
  d.textContent = text;
  tip.appendChild(d);
}
