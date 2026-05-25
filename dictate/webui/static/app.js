const state = { limit: 25, offset: 0, lastCount: 0, entries: [] };
const $ = (id) => document.getElementById(id);
const text = (value) => value ?? "";

function esc(value) {
  return String(value ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
}

function truncate(value, n = 110) {
  const s = text(value);
  return s.length > n ? `${s.slice(0, n)}…` : s;
}

function fmtTs(value) {
  if (!value) return "";
  const d = new Date(value);
  if (isNaN(d.getTime())) return text(value);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function latency(entry) {
  const ms = entry.metrics?.latency_ms;
  return ms == null ? "—" : `${Math.round(ms)} ms`;
}

function entryApp(entry) {
  return entry.frontmost?.app_name || entry.frontmost?.bundle_id || "";
}

async function loadList() {
  const tbody = $("transcripts");
  if (!tbody) return;
  const params = new URLSearchParams({ limit: state.limit, offset: state.offset });
  if ($("search")?.value) params.set("q", $("search").value);
  if ($("preset")?.value) params.set("preset", $("preset").value);
  if ($("app")?.value) params.set("app", $("app").value);
  if ($("since")?.value) params.set("since", $("since").value);
  const res = await fetch(`/api/transcripts?${params}`);
  state.entries = await res.json();
  state.lastCount = state.entries.length;
  tbody.innerHTML = state.entries.length ? state.entries.map(rowHtml).join("") : `<tr><td colspan="6" class="muted">No entries</td></tr>`;
  $("page-label").textContent = `Page ${Math.floor(state.offset / state.limit) + 1}`;
  $("prev").disabled = state.offset === 0;
  $("next").disabled = state.lastCount < state.limit;
  selectRow(0);
}

function rowHtml(entry) {
  const raw = entry.raw || entry.cleaned || "";
  const ts = fmtTs(entry.ts);
  const url = `/entry/${encodeURIComponent(entry.id)}`;
  return `<tr data-entry-url="${url}" tabindex="0">
    <td class="ts">${esc(ts)}</td>
    <td>${esc(entry.preset || "default")}</td>
    <td>${esc(entryApp(entry)) || "—"}</td>
    <td class="raw">${esc(truncate(raw))}</td>
    <td class="latency">${esc(latency(entry))}</td>
    <td class="actions">
      <button class="ghost" data-delete="${esc(entry.id)}" aria-label="Delete transcript">Delete</button>
    </td>
  </tr>`;
}

async function removeEntry(id) {
  if (!confirm("Delete this transcript?")) return;
  await fetch(`/api/transcripts/${encodeURIComponent(id)}`, { method: "DELETE", headers: { "X-Dictate-WebUI": "1" } });
  if ($("transcripts")) await loadList();
  if ($("detail")) location.href = "/";
}

function transcriptRows() {
  return Array.from(document.querySelectorAll("#transcripts tr[data-entry-url]"));
}

function selectRow(index) {
  const rows = transcriptRows();
  rows.forEach((row) => row.classList.remove("selected"));
  if (!rows.length) return;
  const nextIndex = Math.max(0, Math.min(index, rows.length - 1));
  rows[nextIndex].classList.add("selected");
  rows[nextIndex].scrollIntoView({ block: "nearest" });
}

function selectedRowIndex() {
  return transcriptRows().findIndex((row) => row.classList.contains("selected"));
}

function moveSelection(delta) {
  const rows = transcriptRows();
  if (!rows.length) return;
  const current = selectedRowIndex();
  selectRow((current === -1 ? 0 : current) + delta);
}

function openSelected() {
  const row = transcriptRows().find((item) => item.classList.contains("selected"));
  if (row?.dataset.entryUrl) location.href = row.dataset.entryUrl;
}

function isTypingTarget(target) {
  return target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement || target?.isContentEditable;
}

function wireShortcuts() {
  document.addEventListener("keydown", (event) => {
    if (isTypingTarget(event.target)) return;
    if (event.key === "/") {
      const search = $("search");
      if (search) { event.preventDefault(); search.focus(); }
    } else if (event.key === "j") {
      event.preventDefault();
      moveSelection(1);
    } else if (event.key === "k") {
      event.preventDefault();
      moveSelection(-1);
    } else if (event.key === "o") {
      event.preventDefault();
      openSelected();
    } else if (event.key === "?") {
      const help = $("shortcut-help");
      if (help) { event.preventDefault(); help.focus(); }
    }
  });
}

function wireList() {
  if (!$("transcripts")) return;
  ["search", "preset", "app", "since"].forEach((id) => $(id).addEventListener("input", debounce(() => { state.offset = 0; loadList(); }, 250)));
  $("refresh").addEventListener("click", loadList);
  $("prev").addEventListener("click", () => { state.offset = Math.max(0, state.offset - state.limit); loadList(); });
  $("next").addEventListener("click", () => { state.offset += state.limit; loadList(); });
  const purgeForm = $("purge-form");
  if (purgeForm) {
    purgeForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const days = Number($("purge-days").value);
      if (!days || days < 1) return;
      if (!confirm(`Delete all transcripts older than ${days} days?`)) return;
      const res = await fetch("/api/purge", { method: "POST", headers: { "Content-Type": "application/json", "X-Dictate-WebUI": "1" }, body: JSON.stringify({ older_than_days: days }) });
      const data = await res.json();
      const summary = $("purge-form").querySelector(".purge-result") || document.createElement("span");
      summary.className = "purge-result muted";
      summary.textContent = `Deleted ${data.deleted} entries`;
      purgeForm.appendChild(summary);
      loadList();
    });
  }
  document.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    if (target.dataset.delete) { event.stopPropagation(); await removeEntry(target.dataset.delete); return; }
    const row = target.closest("tr[data-entry-url]");
    if (row) {
      selectRow(transcriptRows().indexOf(row));
      if (!target.closest("button, a, input")) {
        window.location.href = row.dataset.entryUrl;
      }
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    const row = document.activeElement?.closest("tr[data-entry-url]");
    if (row) window.location.href = row.dataset.entryUrl;
  });
  loadList();
}

async function loadDetail() {
  const detail = $("detail");
  if (!detail) return;
  const id = detail.dataset.entryId;
  const res = await fetch(`/api/transcripts/${encodeURIComponent(id)}`);
  if (!res.ok) { $("detail-content").textContent = "Entry not found"; return; }
  const entry = await res.json();
  renderDetailHeader(entry);
  $("detail-content").classList.remove("muted");
  $("detail-content").innerHTML = detailHtml(entry);
  $("delete-detail").onclick = async () => {
    if (!confirm("Delete this transcript?")) return;
    await removeEntry(entry.id);
    window.location.href = "/";
  };
  $("copy-cleaned").onclick = () => copyWithFlash("copy-cleaned", text(entry.cleaned));
  $("copy-raw").onclick = () => copyWithFlash("copy-raw", text(entry.raw));
}

function copyWithFlash(id, value) {
  navigator.clipboard.writeText(value);
  const btn = $(id);
  if (!btn) return;
  const original = btn.textContent;
  btn.textContent = "Copied";
  btn.disabled = true;
  setTimeout(() => { btn.textContent = original; btn.disabled = false; }, 900);
}

function renderDetailHeader(entry) {
  const time = $("detail-time");
  if (time) time.textContent = fmtTs(entry.ts) || "Transcript";
  const chips = $("detail-chips");
  if (chips) {
    const items = [
      ["Preset", entry.preset || "default"],
      ["App", entryApp(entry)],
      ["Latency", latency(entry)],
      ["Backend", entry.metrics?.cleanup_backend || entry.backend || "—"],
      ["Characters", String(text(entry.cleaned).length || text(entry.raw).length || 0)],
    ];
    chips.innerHTML = items
      .filter(([, v]) => v && v !== "—")
      .map(([k, v]) => `<span class="chip"><span class="chip-key">${esc(k)}</span><span class="chip-val">${esc(v)}</span></span>`)
      .join("");
  }
  const nav = $("entry-nav");
  if (nav) {
    const neighbors = entry._neighbors || {};
    const prev = neighbors.prev
      ? `<a class="nav-arrow" href="/entry/${encodeURIComponent(neighbors.prev)}" title="Newer entry">← Newer</a>`
      : `<span class="nav-arrow disabled">← Newer</span>`;
    const next = neighbors.next
      ? `<a class="nav-arrow" href="/entry/${encodeURIComponent(neighbors.next)}" title="Older entry">Older →</a>`
      : `<span class="nav-arrow disabled">Older →</span>`;
    nav.innerHTML = prev + next;
  }
}

function detailHtml(entry) {
  const raw = text(entry.raw);
  const cleaned = text(entry.cleaned);
  const identical = raw.trim() === cleaned.trim();
  const transcriptBlock = identical
    ? `<section class="panel">
         <div class="panel-head"><h2>Transcript</h2><span class="badge subtle">No edits</span></div>
         <pre class="transcript-pre">${esc(raw || cleaned)}</pre>
       </section>`
    : `<section class="panel">
         <div class="panel-head"><h2>Transcript</h2><span class="badge subtle">Cleaned by model</span></div>
         <div class="diff">
           <div><h3>Raw</h3><pre class="transcript-pre">${esc(raw)}</pre></div>
           <div><h3>Cleaned</h3><pre class="transcript-pre">${esc(cleaned)}</pre></div>
         </div>
         ${diffHtml(raw, cleaned)}
       </section>`;
  const selection = entry.selection
    ? `<section class="panel"><h2>Selection context</h2><pre class="transcript-pre">${esc(entry.selection)}</pre></section>`
    : "";
  const redactions = redactionsHtml(entry.redactions);
  const metrics = metricsHtml(entry.metrics);
  return transcriptBlock + selection + redactions + metrics;
}

function redactionsHtml(redactions) {
  const list = Array.isArray(redactions) ? redactions : [];
  if (list.length === 0) {
    return `<section class="panel"><div class="panel-head"><h2>Redactions</h2><span class="badge subtle">None</span></div></section>`;
  }
  const rows = list.map(r => `<tr><td>${esc(r.kind || r.type || "—")}</td><td><code>${esc(r.placeholder || r.token || "—")}</code></td><td>${esc(r.span ? r.span.join("–") : "—")}</td></tr>`).join("");
  return `<section class="panel">
    <div class="panel-head"><h2>Redactions</h2><span class="badge subtle">${list.length}</span></div>
    <table class="meta-table"><thead><tr><th>Kind</th><th>Placeholder</th><th>Span</th></tr></thead><tbody>${rows}</tbody></table>
  </section>`;
}

function metricsHtml(metrics) {
  const m = metrics || {};
  const keys = Object.keys(m);
  if (keys.length === 0) {
    return `<section class="panel"><div class="panel-head"><h2>Metrics</h2><span class="badge subtle">None recorded</span></div></section>`;
  }
  const order = ["latency_ms", "asr_ms", "cleanup_ms", "paste_ms", "duration_ms", "cleanup_backend", "cleanup_model", "cleanup_skipped", "fallback_used"];
  const sorted = [...keys].sort((a, b) => {
    const ai = order.indexOf(a), bi = order.indexOf(b);
    if (ai !== -1 && bi !== -1) return ai - bi;
    if (ai !== -1) return -1;
    if (bi !== -1) return 1;
    return a.localeCompare(b);
  });
  const fmt = (k, v) => {
    if (v == null) return "—";
    if (k.endsWith("_ms") && typeof v === "number") return `${v.toLocaleString()} ms`;
    if (typeof v === "boolean") return v ? "yes" : "no";
    return String(v);
  };
  const rows = sorted.map(k => `<div class="dl-row"><dt>${esc(metricLabel(k))}</dt><dd>${esc(fmt(k, m[k]))}</dd></div>`).join("");
  return `<section class="panel"><h2>Metrics</h2><dl class="dl-grid">${rows}</dl></section>`;
}

function metricLabel(key) {
  const labels = {
    latency_ms: "Latency",
    asr_ms: "ASR",
    cleanup_ms: "Cleanup",
    paste_ms: "Paste",
    duration_ms: "Total",
    cleanup_backend: "Backend",
    cleanup_model: "Model",
    cleanup_skipped: "Cleanup skipped",
    fallback_used: "Fallback used",
  };
  return labels[key] || key.replace(/_/g, " ");
}

function diffHtml(a, b) {
  const left = text(a).split(/\n/);
  const right = text(b).split(/\n/);
  const rows = [];
  const count = Math.max(left.length, right.length);
  for (let i = 0; i < count; i++) {
    const same = left[i] === right[i];
    rows.push(`<div class="${same ? "" : "removed"}">${esc(left[i])}</div><div class="${same ? "" : "added"}">${esc(right[i])}</div>`);
  }
  return `<h2>Line diff</h2><div class="diff"><pre>${rows.join("\n")}</pre></div>`;
}

const BACKEND_LABELS = {
  ollama: "Ollama (local)",
  openrouter: "OpenRouter",
  openai: "OpenAI",
  raw: "Raw passthrough",
  skipped: "No-op (clean as-is)",
  unknown: "Unknown",
};

function relabel(map, labels) {
  const out = {};
  for (const [k, v] of Object.entries(map || {})) {
    out[labels[k] || k] = (out[labels[k] || k] || 0) + v;
  }
  return out;
}

function fmtMs(v) { return v == null ? "—" : `${Math.round(v)} ms`; }

async function loadStats() {
  if (!$("stats-cards")) return;
  const stats = await (await fetch("/api/stats")).json();
  const localPct = Math.round((stats.local_ratio ?? 1) * 100);
  $("stats-cards").innerHTML = [
    ["Total utterances", (stats.total ?? 0).toLocaleString(), `${(stats.total_chars ?? 0).toLocaleString()} chars dictated`],
    ["Avg length", `${Math.round(stats.avg_chars ?? 0)} chars`, "per utterance"],
    ["Median latency", fmtMs(stats.p50_latency_ms ?? stats.avg_latency_ms), `p95 ${fmtMs(stats.p95_latency_ms)}`],
    ["100% local", `${localPct}%`, "of utterances stayed on-device"],
    ["Fallback rate", `${Math.round((stats.fallback_rate ?? 0) * 100)}%`, "cleanup → raw"],
  ].map(([label, value, sub]) => `<div class="card">${esc(label)}<strong>${esc(value)}</strong><span class="card-sub muted">${esc(sub)}</span></div>`).join("");
  drawBar("day-chart", formatDayKeys(stats.by_day), "Utterances", { highlightLast: true });
  renderDayAxis("day-chart-axis", stats.by_day || {});
  const hourMap = {};
  for (let h = 0; h < 24; h++) hourMap[String(h).padStart(2, "0")] = (stats.by_hour || {})[h] ?? (stats.by_hour || {})[String(h)] ?? 0;
  drawBar("hour-chart", hourMap, "Utterances");
  renderHourAxis("hour-chart-axis");
  drawPie("preset-chart", stats.by_preset);
  drawPie("backend-chart", relabel(stats.by_backend, BACKEND_LABELS));
  const foot = $("backend-foot");
  if (foot) foot.textContent = "“No-op” means the dictation was clean enough that no cleanup model was needed. “Raw” means cleanup was attempted but the result was rejected (kept the original).";
  drawBar("app-chart", stats.by_app, "Utterances");
}

function renderDayAxis(id, byDay) {
  const el = $(id);
  if (!el) return;
  const keys = Object.keys(byDay || {});
  if (!keys.length) { el.innerHTML = ""; return; }
  const ticks = [0, Math.floor(keys.length / 2), keys.length - 1];
  const labels = ticks.map((i) => {
    const k = keys[i];
    if (!k) return "";
    const d = new Date(k);
    return isNaN(d.getTime()) ? k : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  });
  el.innerHTML = labels.map((l) => `<span>${esc(l)}</span>`).join("");
}

function renderHourAxis(id) {
  const el = $(id);
  if (!el) return;
  el.innerHTML = ["00", "06", "12", "18", "23"].map((l) => `<span>${l}</span>`).join("");
}

function chartColors(n) {
  // Generated from a fixed seed so charts look consistent across reloads.
  const palette = ["#06B6D4", "#3B82F6", "#8B5CF6", "#EC4899", "#F59E0B", "#10B981", "#EF4444", "#6366F1", "#14B8A6", "#A855F7"];
  return Array.from({ length: n }, (_, i) => palette[i % palette.length]);
}

function setupCanvas(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const cssWidth = rect.width || canvas.parentElement?.clientWidth || 320;
  const cssHeight = rect.height || 220;
  canvas.width = Math.round(cssWidth * dpr);
  canvas.height = Math.round(cssHeight * dpr);
  canvas.style.width = `${cssWidth}px`;
  canvas.style.height = `${cssHeight}px`;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, cssWidth, cssHeight);
  return { ctx, w: cssWidth, h: cssHeight };
}

function chartTheme() {
  const styles = getComputedStyle(document.documentElement);
  return {
    fg: styles.getPropertyValue("--fg").trim() || "#1a1a1a",
    muted: styles.getPropertyValue("--muted").trim() || "#888",
    bg: styles.getPropertyValue("--bg").trim() || "#fff",
  };
}

function drawEmpty(ctx, w, h, theme) {
  ctx.fillStyle = theme.muted;
  ctx.font = "13px -apple-system, BlinkMacSystemFont, 'Helvetica Neue', sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText("No data yet", w / 2, h / 2);
}

function formatDayKeys(byDay) {
  if (!byDay) return {};
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const out = {};
  for (const [key, value] of Object.entries(byDay)) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(key);
    if (m) {
      const month = months[parseInt(m[2], 10) - 1] || m[2];
      out[`${month} ${parseInt(m[3], 10)}`] = value;
    } else {
      out[key] = value;
    }
  }
  return out;
}

function drawBar(id, data, label, opts = {}) {
  const canvas = $(id);
  if (!canvas) return;
  const { ctx, w, h } = setupCanvas(canvas);
  const theme = chartTheme();
  const entries = Object.entries(data || {});
  const max = entries.reduce((acc, [, v]) => Math.max(acc, Number(v) || 0), 0);
  if (entries.length === 0 || max === 0) { drawEmpty(ctx, w, h, theme); return; }

  const padL = 40, padR = 12, padT = 12, padB = 36;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;
  const accent = (getComputedStyle(document.documentElement).getPropertyValue("--accent") || "#06B6D4").trim();
  const singleColor = opts.singleColor !== false && entries.length > 8;
  const colors = singleColor ? entries.map(() => accent) : chartColors(entries.length);

  ctx.strokeStyle = theme.muted;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(padL, padT);
  ctx.lineTo(padL, padT + plotH);
  ctx.lineTo(padL + plotW, padT + plotH);
  ctx.stroke();
  ctx.fillStyle = theme.muted;
  ctx.font = "11px -apple-system, BlinkMacSystemFont, sans-serif";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  ctx.fillText(String(max), padL - 6, padT);
  ctx.fillText("0", padL - 6, padT + plotH);

  const barGap = entries.length > 12 ? 1 : 3;
  const barW = Math.max(2, (plotW - barGap * (entries.length - 1)) / entries.length);

  entries.forEach(([key, value], i) => {
    const v = Number(value) || 0;
    const barH = (v / max) * plotH;
    const x = padL + i * (barW + barGap);
    const y = padT + plotH - barH;
    ctx.fillStyle = colors[i];
    if (singleColor) {
      const isLast = opts.highlightLast && i === entries.length - 1;
      ctx.globalAlpha = v === 0 ? 0.25 : (isLast ? 1.0 : 0.7);
    }
    ctx.fillRect(x, y, barW, Math.max(barH, v > 0 ? 2 : 0));
    ctx.globalAlpha = 1.0;

    if (entries.length <= 14) {
      ctx.fillStyle = theme.muted;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      const labelStr = String(key).length > 10 ? String(key).slice(0, 9) + "…" : String(key);
      ctx.fillText(labelStr, x + barW / 2, padT + plotH + 6);
    }
  });

  ctx.fillStyle = theme.muted;
  ctx.textAlign = "left";
  ctx.textBaseline = "alphabetic";
  ctx.font = "10px -apple-system, BlinkMacSystemFont, sans-serif";
  ctx.fillText(label || "", padL, h - 4);
}

function drawPie(id, data) {
  const canvas = $(id);
  if (!canvas) return;
  const { ctx, w, h } = setupCanvas(canvas);
  const theme = chartTheme();
  const entries = Object.entries(data || {}).filter(([, v]) => Number(v) > 0);
  const total = entries.reduce((acc, [, v]) => acc + Number(v), 0);
  if (total === 0) { drawEmpty(ctx, w, h, theme); return; }

  const legendW = 170;
  const cx = (w - legendW) / 2 + 8;
  const cy = h / 2;
  const radius = Math.min(w - legendW, h) / 2 - 12;
  const innerR = radius * 0.55;
  const colors = chartColors(entries.length);

  let angle = -Math.PI / 2;
  entries.forEach(([, v], i) => {
    const slice = (Number(v) / total) * Math.PI * 2;
    ctx.fillStyle = colors[i];
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, radius, angle, angle + slice);
    ctx.closePath();
    ctx.fill();
    angle += slice;
  });
  // inner cutout for doughnut
  ctx.globalCompositeOperation = "destination-out";
  ctx.beginPath();
  ctx.arc(cx, cy, innerR, 0, Math.PI * 2);
  ctx.fill();
  ctx.globalCompositeOperation = "source-over";

  // legend
  ctx.font = "12px -apple-system, BlinkMacSystemFont, sans-serif";
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  const legendX = w - legendW + 8;
  const rowH = 18;
  const startY = cy - (entries.length * rowH) / 2 + rowH / 2;
  entries.forEach(([key, v], i) => {
    const y = startY + i * rowH;
    ctx.fillStyle = colors[i];
    ctx.fillRect(legendX, y - 6, 10, 12);
    ctx.fillStyle = theme.fg;
    const label = String(key).length > 18 ? String(key).slice(0, 17) + "…" : String(key);
    const pct = Math.round((Number(v) / total) * 100);
    ctx.fillText(`${label} · ${pct}%`, legendX + 16, y);
  });
}

function debounce(fn, ms) {
  let timer;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); };
}

document.addEventListener("DOMContentLoaded", () => { wireShortcuts(); wireList(); loadDetail(); loadStats(); loadDashboard(); });

async function loadDashboard() {
  const recentList = $("recent-list");
  const healthList = $("health-list");
  if (!recentList && !healthList) return;
  let data;
  try {
    const res = await fetch("/api/dashboard");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
  } catch (err) {
    if (recentList) recentList.innerHTML = `<li class="muted recent-empty">Could not load dashboard: ${esc(err.message)}</li>`;
    return;
  }
  renderDashboardKpis(data);
  renderRecent(data.recent || []);
  renderHealth(data.health || {});
  renderSuggestions(data.suggestions || []);
}

function renderDashboardKpis(data) {
  const today = data.today || {};
  const totals = data.totals || {};
  const setText = (id, value) => { const el = $(id); if (el) el.textContent = value; };
  setText("kpi-today-count", today.count ?? 0);
  setText("kpi-today-chars", (today.chars ?? 0).toLocaleString());
  setText("kpi-today-words", today.chars ? `≈ ${Math.round(today.chars / 5).toLocaleString()} words` : "no characters yet");
  setText("kpi-today-latency", today.avg_latency_ms == null ? "—" : `${Math.round(today.avg_latency_ms)} ms`);
  setText("kpi-total", (totals.entries ?? 0).toLocaleString());
  setText("kpi-last-updated", totals.last_updated ? `last entry ${fmtTs(totals.last_updated)}` : "no entries yet");
  const rate = $("kpi-today-rate");
  if (rate) {
    if ((today.count ?? 0) === 0) rate.textContent = "no dictations yet today";
    else if ((today.fallback_rate ?? 0) > 0) rate.textContent = `${Math.round(today.fallback_rate * 100)}% used fallback`;
    else rate.textContent = "all clean ✓";
  }
  setText("hero-hotkey", data.hotkey || "⌘H");
  drawSparkline("kpi-sparkline", data.sparkline_7d || []);
}

function drawSparkline(id, points) {
  const canvas = $(id);
  if (!canvas) return;
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.width || 120;
  const cssH = canvas.height || 36;
  canvas.width = cssW * dpr;
  canvas.height = cssH * dpr;
  canvas.style.width = `${cssW}px`;
  canvas.style.height = `${cssH}px`;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, cssW, cssH);
  const theme = chartTheme();
  const counts = points.map((p) => Number(p.count) || 0);
  const max = Math.max(1, ...counts);
  if (counts.length === 0) return;
  const padX = 2, padY = 4;
  const barW = Math.max(2, (cssW - padX * 2 - (counts.length - 1) * 2) / counts.length);
  const accent = (getComputedStyle(document.documentElement).getPropertyValue("--accent") || "#06B6D4").trim();
  counts.forEach((v, i) => {
    const h = Math.max(2, (v / max) * (cssH - padY * 2));
    const x = padX + i * (barW + 2);
    const y = cssH - padY - h;
    ctx.fillStyle = v === 0 ? theme.muted : accent;
    ctx.globalAlpha = v === 0 ? 0.3 : (i === counts.length - 1 ? 1.0 : 0.65);
    roundRect(ctx, x, y, barW, h, 2);
    ctx.fill();
  });
  ctx.globalAlpha = 1.0;
}

function roundRect(ctx, x, y, w, h, r) {
  const radius = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.arcTo(x + w, y, x + w, y + h, radius);
  ctx.arcTo(x + w, y + h, x, y + h, radius);
  ctx.arcTo(x, y + h, x, y, radius);
  ctx.arcTo(x, y, x + w, y, radius);
  ctx.closePath();
}

function renderSuggestions(items) {
  const panel = $("suggestions-panel");
  const list = $("suggestions-list");
  if (!panel || !list) return;
  if (!items || items.length === 0) { panel.hidden = true; return; }
  panel.hidden = false;
  list.innerHTML = items.map((s) => `
    <li class="suggestion suggestion-${esc(s.kind || "info")}">
      <div class="suggestion-body">
        <strong>${esc(s.title)}</strong>
        <span class="muted small">${esc(s.detail)}</span>
      </div>
      ${s.action_label ? `<a class="suggestion-action" href="${esc(s.action_href || "#")}">${esc(s.action_label)}</a>` : ""}
    </li>
  `).join("");
}

function relativeDayLabel(ts) {
  if (!ts) return "Earlier";
  const d = new Date(ts);
  if (isNaN(d.getTime())) return "Earlier";
  const now = new Date();
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const diffDays = Math.floor((startToday - new Date(d.getFullYear(), d.getMonth(), d.getDate())) / 86400000);
  if (diffDays === 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return d.toLocaleDateString(undefined, { weekday: "long" });
  return "Earlier";
}

function fmtTime(ts) {
  if (!ts) return "";
  const d = new Date(ts);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function renderRecent(items) {
  const list = $("recent-list");
  if (!list) return;
  if (!items.length) {
    list.innerHTML = `<li class="muted recent-empty">No dictations yet. Hold your hotkey to start.</li>`;
    return;
  }
  let lastGroup = null;
  const rows = [];
  for (const entry of items) {
    const group = relativeDayLabel(entry.ts);
    if (group !== lastGroup) {
      rows.push(`<li class="recent-group">${esc(group)}</li>`);
      lastGroup = group;
    }
    const text = truncate(entry.cleaned || entry.raw || "", 90);
    const time = fmtTime(entry.ts);
    const app = entryApp(entry);
    const lat = latency(entry);
    const preset = entry.preset || "default";
    const url = `/entry/${encodeURIComponent(entry.id)}`;
    rows.push(`<li><a class="recent-item" href="${url}">
      <span class="recent-time">${esc(time)}</span>
      <span class="recent-text">${esc(text) || "<em>empty</em>"}</span>
      <span class="recent-meta">
        <span class="preset-badge preset-${esc(preset)}">${esc(preset)}</span>
        ${app ? `<span class="recent-app">${esc(app)}</span>` : ""}
        <span>${esc(lat)}</span>
      </span>
    </a></li>`);
  }
  list.innerHTML = rows.join("");
}

function renderHealth(health) {
  const list = $("health-list");
  if (!list) return;
  const rows = [];
  const backend = health.backend || {};
  if (health.cleanup_enabled === false) {
    rows.push(healthRow("ok", "Cleanup", "Disabled — raw + smart punctuation"));
  } else {
    const backendState = backend.ok ? "ok" : (backend.error ? "bad" : "warn");
    const backendDetail = backend.ok
      ? `${backend.host || backend.url || ""} · ${backend.latency_ms ?? "?"} ms`
      : (backend.error || "unreachable");
    rows.push(healthRow(backendState, `Backend · ${esc(health.active_backend || "—")}`, backendDetail));

    const configured = health.configured_model;
    const resolved = health.resolved_model;
    if (configured || resolved) {
      let state = "ok"; let detail = esc(configured || "");
      if (resolved && configured && resolved !== configured) {
        state = "warn";
        detail = `${esc(configured)} → using ${esc(resolved)}`;
      } else if (resolved) {
        detail = esc(resolved);
      }
      rows.push(healthRow(state, "Cleanup model", detail));
    }
  }

  const perms = Array.isArray(health.permissions) ? health.permissions : [];
  for (const perm of perms) {
    rows.push(healthRow(perm.granted ? "ok" : "bad", `Permission · ${esc(perm.label)}`, perm.granted ? "granted" : "not granted"));
  }
  list.innerHTML = rows.join("") || `<li class="muted">No health checks available.</li>`;
}

function healthRow(state, label, detail) {
  return `<li class="health-row">
    <span class="health-dot ${esc(state)}" aria-hidden="true"></span>
    <span class="health-label">${label}</span>
    <span class="health-detail" title="${esc(detail)}">${esc(detail)}</span>
  </li>`;
}
