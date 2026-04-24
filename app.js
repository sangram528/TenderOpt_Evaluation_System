/**
 * app.js — CRPF Tender Evaluation UI
 *
 * State is kept in a plain object.
 * When scanner.py + verdict.py are integrated, replace
 * the simulateEvaluation() function with real API calls.
 */

// ─────────────────────────────────────────────
// STATE
// ─────────────────────────────────────────────
function toggleTheme() {
    const isLight = document.body.classList.toggle("light");
    document.getElementById("theme-icon").textContent = isLight ? "☾" : "☀";
    localStorage.setItem("theme", isLight ? "light" : "dark");
  }
  
  // Remember preference on reload
  if (localStorage.getItem("theme") === "light") {
    document.body.classList.add("light");
    document.getElementById("theme-icon").textContent = "☾";
  }
const state = {
    tenderFile:  null,
    bidderFiles: [],
    results:     null,    // filled after evaluation
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
    updateFilesPane();
    checkRunReady();
  });
  
  document.getElementById("bidder-file").addEventListener("change", function () {
    for (const file of this.files) {
      if (!state.bidderFiles.find(f => f.name === file.name))
        state.bidderFiles.push(file);
    }
    renderBidderList();
    checkRunReady();
    this.value = "";  // reset input so same file can be re-added if removed
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
  
  // Drag-and-drop on upload zones
  ["tender-zone", "bidder-zone"].forEach(id => {
    const zone = document.getElementById(id);
    zone.addEventListener("dragover", e => { e.preventDefault(); zone.classList.add("drag-over"); });
    zone.addEventListener("dragleave", ()  => zone.classList.remove("drag-over"));
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
  function updateFilesPane() {
    // Tender preview
    const tenderBox = document.getElementById("tender-preview");
    if (state.tenderFile) {
      const size = (state.tenderFile.size / 1024).toFixed(0) + " KB";
      tenderBox.innerHTML = `
        <div class="file-preview-item">
          <span class="fpi-icon">⬡</span>
          <span class="fpi-name">${state.tenderFile.name}</span>
          <span class="fpi-size">${size}</span>
        </div>`;
    } else {
      tenderBox.innerHTML = `<div class="file-preview-empty">No tender uploaded yet</div>`;
    }
  
    // Bidder previews
    const bidderBox = document.getElementById("bidder-preview");
    if (state.bidderFiles.length === 0) {
      bidderBox.innerHTML = `<div class="file-preview-empty">No bidders uploaded yet</div>`;
    } else {
      bidderBox.innerHTML = state.bidderFiles.map((f, i) => {
        const size = (f.size / 1024).toFixed(0) + " KB";
        return `
          <div class="file-preview-item">
            <span class="fpi-icon">⬡</span>
            <span class="fpi-name">${f.name}</span>
            <span class="fpi-size">${size}</span>
          </div>`;
      }).join("");
    }
  }
  
  // ─────────────────────────────────────────────
  // RUN EVALUATION
  // ─────────────────────────────────────────────
  
  async function runEvaluation() {
    document.getElementById("run-btn").disabled = true;
    document.getElementById("empty-state").hidden = true;
    document.getElementById("results-content").hidden = false;
  
    // Show loading
    const panel = document.getElementById("results-content");
    panel.innerHTML = `
      <div class="loading-label" id="loading-label">Initialising scanner…</div>
      <div class="loading-bar"><div class="loading-bar-inner" id="loading-bar"></div></div>`;
  
    // Simulate pipeline stages
    // ─────────────────────────────────────────────────────────────────────
    // INTEGRATION POINT
    // When scanner.py + verdict.py are ready, replace simulateEvaluation()
    // with a real fetch() call to your Python backend:
    //
    //   const formData = new FormData();
    //   formData.append("tender", state.tenderFile);
    //   state.bidderFiles.forEach(f => formData.append("bidders", f));
    //   const res = await fetch("/api/evaluate", { method: "POST", body: formData });
    //   const results = await res.json();
    //   renderResults(results);
    // ─────────────────────────────────────────────────────────────────────
  
    const results = await simulateEvaluation();
    state.results = results;
    renderResults(results);
  }
  
  async function simulateEvaluation() {
    const stages = [
      [15,  "Parsing tender document…"],
      [30,  "Extracting eligibility criteria…"],
      [48,  "Scanning bidder submissions…"],
      [62,  "Running OCR on scanned documents…"],
      [74,  "Verifying GST numbers against government records…"],
      [86,  "Comparing specifications criterion by criterion…"],
      [95,  "Generating evaluation report…"],
      [100, "Done."],
    ];
  
    for (const [pct, label] of stages) {
      await sleep(420 + Math.random() * 300);
      setProgress(pct, label);
    }
  
    await sleep(300);
    return DUMMY_RESULTS;
  }
  
  function setProgress(pct, label) {
    const bar   = document.getElementById("loading-bar");
    const lbl   = document.getElementById("loading-label");
    if (bar)  bar.style.width  = pct + "%";
    if (lbl)  lbl.textContent  = label;
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
    renderBidderSelectOptions(data.bidders);
    renderAuditLog(data.bidders);
  
    document.getElementById("run-btn").disabled = false;
  }
  
  function renderTenderSummary(t) {
    const el = document.getElementById("tender-summary");
    el.innerHTML = `
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
        const isFail = r.toLowerCase().includes("below") || r.toLowerCase().includes("invalid") || r.toLowerCase().includes("not valid");
        return `<div class="bc-reason ${isFail ? "fail" : ""}">${r}</div>`;
      }).join("");
  
      card.innerHTML = `
        <div class="bc-name">${b.bidder_id}</div>
        <div class="bc-company">${b.company_info?.name || "—"}</div>
        <span class="verdict-badge ${badgeClass}">${b.overall_status}</span>
        ${b.reasons.length ? `<div class="bc-reasons">${reasonsHtml}${b.reasons.length > 3 ? `<div class="bc-reason">+ ${b.reasons.length - 3} more issue(s)</div>` : ""}</div>` : ""}`;
  
      grid.appendChild(card);
    });
  }
  
  function renderBidderSelectOptions(bidders) {
    // Store bidders for later access
    state.results.bidders = bidders;
  }
  
  function openDetail(bidderId) {
    switchTab("detail");
    // Rebuild select if needed
    const panel = document.getElementById("tab-detail");
    if (!document.getElementById("bidder-select")) {
      panel.innerHTML = `
        <div class="detail-controls">
          <select id="bidder-select" onchange="renderDetail()"><option value="">Select bidder…</option></select>
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
  
    const table = document.getElementById("detail-table");
    const filter = state.activeFilter;
  
    const rows = bidder.audit_detail.filter(d =>
      filter === "ALL" || d.result === filter
    );
  
    table.innerHTML = `
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
    log.id = "tab-audit";
    const ts = new Date().toLocaleTimeString("en-IN");
  
    let lines = [`<div class="log-line"><span class="log-ts">${ts}</span><span class="log-tag INFO">INFO</span><span class="log-msg">Evaluation started — ${bidders.length} bidder(s)</span></div>`];
  
    bidders.forEach(b => {
      b.audit_detail.forEach(d => {
        lines.push(`
          <div class="log-line">
            <span class="log-ts">${ts}</span>
            <span class="log-tag ${d.result}">${d.result}</span>
            <span class="log-msg">[${b.bidder_id}] ${d.check}${d.note ? " — " + d.note : ""}${d.found ? " → found: " + d.found : ""}</span>
          </div>`);
      });
    });
  
    lines.push(`<div class="log-line"><span class="log-ts">${ts}</span><span class="log-tag INFO">INFO</span><span class="log-msg">Evaluation complete.</span></div>`);
    log.innerHTML = lines.join("");
  }
  
  
  // ─────────────────────────────────────────────
  // TAB SWITCHING
  // ─────────────────────────────────────────────
  
  function switchTab(name) {
    document.querySelectorAll(".tab").forEach((t, i) => {
      const names = ["overview", "detail", "audit"];
      t.classList.toggle("active", names[i] === name);
    });
  
    const tabs = ["tab-overview", "tab-detail", "tab-audit"];
    const map  = { overview: "tab-overview", detail: "tab-detail", audit: "tab-audit" };
  
    tabs.forEach(id => {
      const el = document.getElementById(id);
      if (el) el.hidden = (id !== map[name]);
    });
  
    // If switching to detail and no select exists yet, build it
    if (name === "detail" && !document.getElementById("bidder-select") && state.results) {
      openDetail(state.results.bidders[0]?.bidder_id);
    }
  }
  
  
  // ─────────────────────────────────────────────
  // DUMMY RESULTS
  // This is the exact format the Python backend will return.
  // Replace simulateEvaluation() with a real API call when ready.
  // ─────────────────────────────────────────────
  
  const DUMMY_RESULTS = {
    tender: {
      title:          "T-Shirt Half Sleeves Round Neck Disruptive Pattern",
      authority:      "CRPF HQ, New Delhi",
      criteria_count: 14,
      bidder_count:   2,
      estimated_cost: "₹42,00,000",
    },
    bidders: [
      {
        bidder_id:      "bidder_A_ShivTextiles",
        overall_status: "FLAGGED FOR REVIEW",
        reasons: [
          "Required certification 'ISO 18184' not found in submitted documents",
        ],
        company_info: { name: "SHIV TEXTILES PVT LTD", type: "Private Limited" },
        audit_detail: [
          { check: "Document Quality",          result: "PASS", required: "Clear readable scan", found: "Confidence: 96%" },
          { check: "GST Verification",          result: "PASS", required: "Valid active GSTIN",  found: "27AAPFU0939F1ZV", note: "Active" },
          { check: "PAN Number",                result: "PASS", required: "Valid PAN",            found: "AAPFU0939F" },
          { check: "Certification: ISO 9001",   result: "PASS", required: "ISO 9001",             found: "Present" },
          { check: "Certification: ISO 18184",  result: "FLAG", required: "ISO 18184",            found: "Not found", note: "Certificate must be submitted" },
          { check: "Annual Turnover",           result: "PASS", required: "Rs.5,00,00,000",       found: "Rs.6,50,00,000" },
          { check: "EMD Payment",               result: "PASS", required: "Rs.50,000",            found: "Rs.50,000" },
          { check: "Material: Performance Polyester", result: "PASS", required: "92%",            found: "92%" },
          { check: "Material: Lycra",           result: "PASS", required: "8%",                   found: "8%" },
          { check: "Spec: Seam Strength",       result: "PASS", required: "250 N(Min)",           found: "250 N" },
          { check: "Spec: Fabric Weight",       result: "PASS", required: "180±5%",               found: "180" },
          { check: "Spec: pH Value",            result: "PASS", required: "6.0–8.5",              found: "7.0" },
          { check: "Spec: Bursting Strength",   result: "PASS", required: "100±10",               found: "102" },
          { check: "Spec: Colour Fastness",     result: "PASS", required: "4 or better",          found: "4" },
        ]
      },
      {
        bidder_id:      "bidder_B_RajGarments",
        overall_status: "NOT ELIGIBLE",
        reasons: [
          "Document scan quality low (61%) — originals must be verified manually",
          "GST number 'BADINVALIDGST00' does not match required format",
          "Annual turnover Rs.30,000,000 is below minimum Rs.50,000,000",
          "EMD payment not confirmed in submitted documents",
          "Material composition not stated in bidder documents",
          "4 technical specifications not addressed",
        ],
        company_info: { name: "RAJ GARMENTS", type: "Partnership" },
        audit_detail: [
          { check: "Document Quality",         result: "FLAG", required: "Clear readable scan",  found: "Confidence: 61%",    note: "Low OCR confidence — verify originals" },
          { check: "GST Verification",         result: "FAIL", required: "Valid active GSTIN",   found: "BADINVALIDGST00",    note: "Does not match GSTIN format" },
          { check: "PAN Number",               result: "PASS", required: "Valid PAN",             found: "AAPFU0939F" },
          { check: "Certification: ISO 9001",  result: "FLAG", required: "ISO 9001",              found: "Not found" },
          { check: "Certification: ISO 18184", result: "FLAG", required: "ISO 18184",             found: "Not found" },
          { check: "Annual Turnover",          result: "FAIL", required: "Rs.5,00,00,000",        found: "Rs.3,00,00,000" },
          { check: "EMD Payment",              result: "FLAG", required: "Rs.50,000",             found: "Not confirmed" },
          { check: "Material: Polyester",      result: "FLAG", required: "92%",                   found: "Not stated" },
          { check: "Material: Lycra",          result: "FLAG", required: "8%",                    found: "Not stated" },
          { check: "Spec: Seam Strength",      result: "FLAG", required: "250 N(Min)",            found: "Not stated" },
          { check: "Spec: Fabric Weight",      result: "FLAG", required: "180±5%",                found: "Not stated" },
          { check: "Spec: pH Value",           result: "FLAG", required: "6.0–8.5",               found: "Not stated" },
          { check: "Spec: Bursting Strength",  result: "FLAG", required: "100±10",                found: "Not stated" },
        ]
      }
    ]
  };