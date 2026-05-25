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
  await fetch(`/api/transcripts/${encodeURIComponent(id)}`, { method: "DELETE" });
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
      const res = await fetch("/api/purge", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ older_than_days: days }) });
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

async function loadStats() {
  if (!$("stats-cards")) return;
  const stats = await (await fetch("/api/stats")).json();
  $("stats-cards").innerHTML = [
    ["Total utterances", stats.total],
    ["Characters dictated", stats.total_chars],
    ["Avg latency", stats.avg_latency_ms == null ? "—" : `${Math.round(stats.avg_latency_ms)} ms`],
    ["Fallback rate", `${Math.round(stats.fallback_rate * 100)}%`]
  ].map(([label, value]) => `<div class="card">${label}<strong>${esc(value)}</strong></div>`).join("");
  drawBar("day-chart", formatDayKeys(stats.by_day), "Utterances");
  drawPie("preset-chart", stats.by_preset);
  drawPie("backend-chart", stats.by_backend);
  drawBar("app-chart", stats.by_app, "Utterances");
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

function drawBar(id, data, label) {
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
  const colors = chartColors(entries.length);

  // y-axis baseline + max label
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
    ctx.fillRect(x, y, barW, barH);

    // x label: only render if it'll fit; rotate for dense bars
    if (entries.length <= 14) {
      ctx.fillStyle = theme.muted;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      const labelStr = String(key).length > 10 ? String(key).slice(0, 9) + "…" : String(key);
      ctx.fillText(labelStr, x + barW / 2, padT + plotH + 6);
    }
  });

  // axis title
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

  const legendW = 120;
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
    const label = String(key).length > 12 ? String(key).slice(0, 11) + "…" : String(key);
    const pct = Math.round((Number(v) / total) * 100);
    ctx.fillText(`${label} · ${pct}%`, legendX + 16, y);
  });
}

function debounce(fn, ms) {
  let timer;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); };
}

document.addEventListener("DOMContentLoaded", () => { wireShortcuts(); wireList(); loadDetail(); loadStats(); });
