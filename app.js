/**
 * app.js — CRPF Tender Evaluation UI
 */

// ─────────────────────────────────────────────
// THEME
// ─────────────────────────────────────────────

function toggleTheme() {
  const isLight = document.body.classList.toggle("light");
  document.getElementById("theme-icon").textContent = isLight ? "☾" : "☀";
  localStorage.setItem("theme", isLight ? "light" : "dark");
}

if (localStorage.getItem("theme") === "light") {
  document.body.classList.add("light");
  document.getElementById("theme-icon").textContent = "☾";
}


// ─────────────────────────────────────────────
// STATE
// ─────────────────────────────────────────────

const state = {
  tenderFile:   null,
  bidderFiles:  [],
  results:      null,
  activeFilter: "ALL",
};


// ─────────────────────────────────────────────
// CLOCK
// ─────────────────────────────────────────────

function updateClock() {
  const now = new Date();
  const t = now.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const d = now.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
  document.getElementById("clock").textContent = `${d}  ${t}`;
}
setInterval(updateClock, 1000);
updateClock();


// ─────────────────────────────────────────────
// FILE UPLOAD
// ─────────────────────────────────────────────

function triggerUpload(type) {
  document.getElementById(`${type}-file`).click();
}

document.getElementById("tender-file").addEventListener("change", function () {
  if (!this.files.length) return;
  state.tenderFile = this.files[0];
  document.getElementById("tender-status").textContent = `✓  ${this.files[0].name}`;
  document.getElementById("tender-zone").style.borderColor = "var(--pass)";
  checkRunReady();
  this.value = "";
});

document.getElementById("bidder-file").addEventListener("change", function () {
  for (const file of this.files) {
    if (!state.bidderFiles.find(f => f.name === file.name))
      state.bidderFiles.push(file);
  }
  renderBidderList();
  checkRunReady();
  this.value = "";  // reset so same file can be re-added after removal
});

function renderBidderList() {
  const list = document.getElementById("bidder-list");
  list.innerHTML = "";
  state.bidderFiles.forEach((file, i) => {
    const div = document.createElement("div");
    div.className = "bidder-item";
    div.innerHTML = `
      <span style="color:var(--pass-text);margin-right:6px;font-family:var(--mono)">✓</span>
      <span class="bi-name">${file.name}</span>
      <span class="bi-remove" onclick="removeBidder(${i})">×</span>`;
    list.appendChild(div);
  });
}

function removeBidder(i) {
  state.bidderFiles.splice(i, 1);
  renderBidderList();
  checkRunReady();
}

function checkRunReady() {
  const btn = document.getElementById("run-btn");
  btn.disabled = !(state.tenderFile && state.bidderFiles.length > 0);
}

// Drag-and-drop
["tender-zone", "bidder-zone"].forEach(id => {
  const zone = document.getElementById(id);
  zone.addEventListener("dragover", e => { e.preventDefault(); zone.classList.add("drag-over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("drag-over"));
  zone.addEventListener("drop", e => {
    e.preventDefault();
    zone.classList.remove("drag-over");
    const type = id === "tender-zone" ? "tender" : "bidder";
    if (type === "tender" && e.dataTransfer.files[0]) {
      state.tenderFile = e.dataTransfer.files[0];
      document.getElementById("tender-status").textContent = `✓  ${state.tenderFile.name}`;
      document.getElementById("tender-zone").style.borderColor = "var(--pass)";
    } else {
      for (const file of e.dataTransfer.files) {
        if (!state.bidderFiles.find(f => f.name === file.name))
          state.bidderFiles.push(file);
      }
      renderBidderList();
    }
    checkRunReady();
  });
});


// ─────────────────────────────────────────────
// RUN EVALUATION
// ─────────────────────────────────────────────

async function runEvaluation() {
  document.getElementById("run-btn").disabled = true;
  document.getElementById("empty-state").hidden = true;
  document.getElementById("results-content").hidden = false;

  const panel = document.getElementById("results-content");
  panel.innerHTML = `
    <div class="loading-label" id="loading-label">Uploading documents…</div>
    <div class="loading-bar"><div class="loading-bar-inner" id="loading-bar"></div></div>`;

  try {
    // ── Show progress while waiting for server ──────────────────
    const progressStages = [
      [10, "Uploading documents…"],
      [25, "Parsing tender document…"],
      [45, "Scanning bidder submissions…"],
      [80, "Comparing specifications…"],
      [90, "Generating report…"],
    ];

    // Tick through stages while the fetch runs in parallel
    let stageIndex = 0;
    const ticker = setInterval(() => {
      if (stageIndex < progressStages.length) {
        const [pct, label] = progressStages[stageIndex++];
        setProgress(pct, label);
      }
    }, 900);

    // ── Real API call to main.py ────────────────────────────────
    const formData = new FormData();
    formData.append("tender", state.tenderFile);
    state.bidderFiles.forEach(f => formData.append("bidders", f));

    const res = await fetch("/api/evaluate", {
      method: "POST",
      body:   formData
    });

    clearInterval(ticker);

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "Server error");
    }

    setProgress(100, "Done.");
    await sleep(300);

    const results = await res.json();
    state.results = results;
    renderResults(results);

  } catch (err) {
    // Show error in the results panel — never leave a blank screen
    document.getElementById("results-content").innerHTML = `
      <div style="padding:40px;text-align:center">
        <div style="font-family:var(--mono);color:var(--fail-text);font-size:13px;margin-bottom:8px">
          ✗  Evaluation failed
        </div>
        <div style="color:var(--text-dim);font-size:12px">${err.message}</div>
        <div style="color:var(--text-muted);font-size:11px;margin-top:8px">
          Make sure main.py is running: python main.py
        </div>
      </div>`;
    document.getElementById("run-btn").disabled = false;
  }
}

function setProgress(pct, label) {
  const bar = document.getElementById("loading-bar");
  const lbl = document.getElementById("loading-label");
  if (bar) bar.style.width = pct + "%";
  if (lbl) lbl.textContent = label;
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }


// ─────────────────────────────────────────────
// RENDER RESULTS
// ─────────────────────────────────────────────

function renderResults(data) {
  const panel = document.getElementById("results-content");
  panel.innerHTML = `
    <div id="tender-summary" class="tender-summary"></div>
    <div class="tab-bar">
      <button class="tab active" onclick="switchTab('overview')">Overview</button>
      <button class="tab"        onclick="switchTab('detail')">Criterion Detail</button>
      <button class="tab"        onclick="switchTab('audit')">Audit Log</button>
    </div>
    <div id="tab-overview" class="tab-content"></div>
    <div id="tab-detail"   class="tab-content" hidden></div>
    <div id="tab-audit"    class="tab-content" hidden></div>`;

  renderTenderSummary(data.tender);
  renderOverview(data.bidders);
  state.results.bidders = data.bidders;
  renderAuditLog(data.bidders);
  document.getElementById("run-btn").disabled = false;
}

function renderTenderSummary(t) {
  document.getElementById("tender-summary").innerHTML = `
    <div class="ts-field"><span class="ts-label">Tender</span><span class="ts-value">${t.title}</span></div>
    <div class="ts-field"><span class="ts-label">Authority</span><span class="ts-value">${t.authority}</span></div>
    <div class="ts-field"><span class="ts-label">Criteria</span><span class="ts-value">${t.criteria_count}</span></div>
    <div class="ts-field"><span class="ts-label">Bidders</span><span class="ts-value">${t.bidder_count}</span></div>
    ${t.estimated_cost ? `<div class="ts-field"><span class="ts-label">Est. Cost</span><span class="ts-value">${t.estimated_cost}</span></div>` : ""}`;
}

function renderOverview(bidders) {
  const grid = document.getElementById("tab-overview");
  grid.className = "overview-grid";
  grid.innerHTML = "";

  bidders.forEach(b => {
    const badgeClass = b.overall_status.replace(/\s+/g, "-");
    const card = document.createElement("div");
    card.className = "bidder-card";
    card.onclick = () => openDetail(b.bidder_id);

    const reasonsHtml = b.reasons.slice(0, 3).map(r => {
      const isFail = r.toLowerCase().includes("below") ||
                     r.toLowerCase().includes("invalid") ||
                     r.toLowerCase().includes("not valid");
      return `<div class="bc-reason ${isFail ? "fail" : ""}">${r}</div>`;
    }).join("");

    card.innerHTML = `
      <div class="bc-name">${b.bidder_id}</div>
      <div class="bc-company">${b.company_info?.name || "—"}</div>
      <span class="verdict-badge ${badgeClass}">${b.overall_status}</span>
      ${b.reasons.length ? `
        <div class="bc-reasons">
          ${reasonsHtml}
          ${b.reasons.length > 3 ? `<div class="bc-reason">+ ${b.reasons.length - 3} more issue(s)</div>` : ""}
        </div>` : ""}`;

    grid.appendChild(card);
  });
}

function openDetail(bidderId) {
  switchTab("detail");
  const panel = document.getElementById("tab-detail");

  if (!document.getElementById("bidder-select")) {
    panel.innerHTML = `
      <div class="detail-controls">
        <select id="bidder-select" onchange="renderDetail()">
          <option value="">Select bidder…</option>
        </select>
        <div class="filter-pills">
          <button class="pill active" onclick="toggleFilter(this,'ALL')">All</button>
          <button class="pill" onclick="toggleFilter(this,'PASS')">Pass</button>
          <button class="pill" onclick="toggleFilter(this,'FLAG')">Flag</button>
          <button class="pill" onclick="toggleFilter(this,'FAIL')">Fail</button>
        </div>
      </div>
      <div id="detail-table"></div>`;

    state.results.bidders.forEach(b => {
      const opt = document.createElement("option");
      opt.value = b.bidder_id;
      opt.textContent = b.bidder_id;
      document.getElementById("bidder-select").appendChild(opt);
    });
  }

  document.getElementById("bidder-select").value = bidderId;
  renderDetail();
}

function renderDetail() {
  const select = document.getElementById("bidder-select");
  const bidderId = select?.value;
  if (!bidderId) return;

  const bidder = state.results.bidders.find(b => b.bidder_id === bidderId);
  if (!bidder) return;

  const rows = bidder.audit_detail.filter(d =>
    state.activeFilter === "ALL" || d.result === state.activeFilter
  );

  document.getElementById("detail-table").innerHTML = `
    <div class="criterion-row header">
      <div class="cr-cell hdr">#</div>
      <div class="cr-cell hdr">Check</div>
      <div class="cr-cell hdr">Required</div>
      <div class="cr-cell hdr">Bidder</div>
      <div class="cr-cell hdr">Result</div>
    </div>
    ${rows.map((row, i) => `
    <div class="criterion-row">
      <div class="cr-cell mono dim">${i + 1}</div>
      <div class="cr-cell">${row.check}</div>
      <div class="cr-cell dim">${row.required || row.note || "—"}</div>
      <div class="cr-cell dim">${row.found || "—"}</div>
      <div class="cr-cell"><span class="status-chip ${row.result}">${row.result}</span></div>
    </div>`).join("")}`;
}

function toggleFilter(btn, filter) {
  document.querySelectorAll(".pill").forEach(p => p.classList.remove("active"));
  btn.classList.add("active");
  state.activeFilter = filter;
  renderDetail();
}

function renderAuditLog(bidders) {
  const log = document.getElementById("tab-audit");
  const ts = new Date().toLocaleTimeString("en-IN");

  const lines = [
    `<div class="log-line">
      <span class="log-ts">${ts}</span>
      <span class="log-tag INFO">INFO</span>
      <span class="log-msg">Evaluation started — ${bidders.length} bidder(s)</span>
    </div>`
  ];

  bidders.forEach(b => {
    b.audit_detail.forEach(d => {
      lines.push(`
        <div class="log-line">
          <span class="log-ts">${ts}</span>
          <span class="log-tag ${d.result}">${d.result}</span>
          <span class="log-msg">[${b.bidder_id}] ${d.check}
            ${d.note  ? " — " + d.note  : ""}
            ${d.found ? " → " + d.found : ""}
          </span>
        </div>`);
    });
  });

  lines.push(`
    <div class="log-line">
      <span class="log-ts">${ts}</span>
      <span class="log-tag INFO">INFO</span>
      <span class="log-msg">Evaluation complete.</span>
    </div>`);

  log.innerHTML = lines.join("");
}



function switchTab(name) {
  const names = ["overview", "detail", "audit"];
  document.querySelectorAll(".tab").forEach((t, i) => {
    t.classList.toggle("active", names[i] === name);
  });

  ["tab-overview", "tab-detail", "tab-audit"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.hidden = (id !== `tab-${name}`);
  });

  if (name === "detail" && !document.getElementById("bidder-select") && state.results) {
    openDetail(state.results.bidders[0]?.bidder_id);
  }
}


