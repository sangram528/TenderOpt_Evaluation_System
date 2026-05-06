// ── CLOCK ───────────────────────────────────────────────────────
function pad(n) { return String(n).padStart(2, '0'); }

function updateClock() {
  const now = new Date();
  document.getElementById('clockDate').textContent =
    `${pad(now.getDate())}/${pad(now.getMonth()+1)}/${now.getFullYear()}`;
  document.getElementById('clockTime').textContent =
    `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
}
updateClock();
setInterval(updateClock, 1000);


// ── THEME TOGGLE ────────────────────────────────────────────────
document.getElementById('themeToggle').addEventListener('click', () => {
  const html = document.documentElement;
  const next = html.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
  html.setAttribute('data-theme', next);
  document.getElementById('themeIcon').textContent = next === 'dark' ? '☀' : '☽';
});


// ── STATE ───────────────────────────────────────────────────────
let tenderFile  = null;
let bidderFiles = [];   // array — multiple bidders


// ── TENDER ZONE (single file) ────────────────────────────────────
(function () {
  const zone  = document.getElementById('dropA');
  const input = document.getElementById('fileA');
  const nameEl= document.getElementById('nameA');
  const statEl= document.getElementById('statusA');
  const card  = document.getElementById('cardA');

  zone.addEventListener('click', () => input.click());
  zone.addEventListener('dragover',  e => { e.preventDefault(); zone.classList.add('drag-over'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
  zone.addEventListener('drop', e => {
    e.preventDefault(); zone.classList.remove('drag-over');
    const f = e.dataTransfer.files[0];
    if (f) setTender(f);
  });
  input.addEventListener('change', () => { if (input.files[0]) setTender(input.files[0]); });

  function setTender(f) {
    tenderFile = f;
    nameEl.textContent = f.name;
    statEl.textContent = '● Ready';
    statEl.className   = 'zone-status ready';
    card.classList.add('has-file');
  }
})();


// ── BIDDER ZONE (multiple files) ─────────────────────────────────
(function () {
  const zone   = document.getElementById('dropB');
  const input  = document.getElementById('fileB');
  const nameEl = document.getElementById('nameB');
  const statEl = document.getElementById('statusB');
  const card   = document.getElementById('cardB');
  const listEl = document.getElementById('bidderFileList');

  zone.addEventListener('click', () => input.click());
  zone.addEventListener('dragover',  e => { e.preventDefault(); zone.classList.add('drag-over'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
  zone.addEventListener('drop', e => {
    e.preventDefault(); zone.classList.remove('drag-over');
    addBidderFiles(Array.from(e.dataTransfer.files));
  });
  input.addEventListener('change', () => {
    addBidderFiles(Array.from(input.files));
    input.value = ''; // reset so same file can be re-added if needed
  });

  function addBidderFiles(files) {
    files.forEach(f => {
      if (!bidderFiles.find(x => x.name === f.name && x.size === f.size)) {
        bidderFiles.push(f);
      }
    });
    renderBidderList();
  }

  function renderBidderList() {
    listEl.innerHTML = '';
    bidderFiles.forEach((f, i) => {
      const li = document.createElement('li');
      li.innerHTML = `<span>${esc(f.name)}</span>
        <button class="remove-file" data-i="${i}" title="Remove"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/></svg></button>`;
      listEl.appendChild(li);
    });
    listEl.querySelectorAll('.remove-file').forEach(btn => {
      btn.addEventListener('click', e => {
        e.stopPropagation();
        bidderFiles.splice(Number(btn.dataset.i), 1);
        renderBidderList();
        updateBidderStatus();
      });
    });
    updateBidderStatus();
  }

  function updateBidderStatus() {
    if (bidderFiles.length === 0) {
      nameEl.textContent = 'No documents selected';
      statEl.textContent = '● Pending';
      statEl.className   = 'zone-status pending';
      card.classList.remove('has-file');
    } else {
      nameEl.textContent = `${bidderFiles.length} file(s) selected`;
      statEl.textContent = '● Ready';
      statEl.className   = 'zone-status ready';
      card.classList.add('has-file');
    }
  }
})();


// ── PROCESSING OVERLAY ───────────────────────────────────────────
const procOverlay = document.getElementById('procOverlay');
const procStep    = document.getElementById('procStep');
const procFill    = document.getElementById('procFill');
const ps1 = document.getElementById('ps1');
const ps2 = document.getElementById('ps2');
const ps3 = document.getElementById('ps3');

function showOverlay() { procOverlay.classList.add('active'); }
function hideOverlay() { procOverlay.classList.remove('active'); }

function setStage(pct, msg, active) {
  procFill.style.width = pct + '%';
  procStep.textContent = msg;
  [ps1, ps2, ps3].forEach(el => el.classList.remove('active', 'done'));
  if (active >= 1) ps1.classList.add(active > 1 ? 'done' : 'active');
  if (active >= 2) ps2.classList.add(active > 2 ? 'done' : 'active');
  if (active >= 3) ps3.classList.add(active > 3 ? 'done' : 'active');
}

// Per-bidder progress update
function setStageForBidder(current, total) {
  const pct = Math.round(10 + (current / total) * 75);
  setStage(pct, `Scanning bidder ${current} of ${total}…`, 2);
}


// ── ANALYSE ──────────────────────────────────────────────────────
document.getElementById('analyseBtn').addEventListener('click', async () => {
  if (!tenderFile) {
    alert('Please upload the Tender Document first.');
    return;
  }
  if (bidderFiles.length === 0) {
    alert('Please upload at least one Bidder Document.');
    return;
  }

  // Reset reports
  document.getElementById('reportsSection').classList.remove('visible');
  document.getElementById('reportsList').innerHTML = '';

  showOverlay();
  setStage(5, 'Starting analysis…', 1);

  const reports = [];

  for (let i = 0; i < bidderFiles.length; i++) {
    setStageForBidder(i + 1, bidderFiles.length);

    const formData = new FormData();
    formData.append('tender', tenderFile);
    formData.append('bidder', bidderFiles[i]);

    try {
      const response = await fetch('/compare', { method: 'POST', body: formData });

      if (!response.ok) {
        const err = await response.json().catch(() => ({ error: `Server error ${response.status}` }));
        reports.push({ filename: bidderFiles[i].name, error: err.error || `Server error ${response.status}` });
      } else {
        const report = await response.json();
        reports.push({ filename: bidderFiles[i].name, ...report });
      }
    } catch (err) {
      reports.push({ filename: bidderFiles[i].name, error: err.message || 'Network error.' });
    }
  }

  setStage(100, 'Analysis complete.', 4);

  setTimeout(() => {
    hideOverlay();
    renderReports(reports);
  }, 600);
});


// ── RENDER REPORTS ───────────────────────────────────────────────
function renderReports(reports) {
  const list = document.getElementById('reportsList');
  list.innerHTML = '';

  reports.forEach((r, idx) => {
    const card = document.createElement('div');

    if (r.error) {
      card.className = 'report-card flagged';
      card.innerHTML = `
        <div class="report-card-header" onclick="toggleCard(this)">
          <span class="report-filename">${esc(r.filename)}</span>
          <span class="report-verdict-badge flagged">ERROR</span>
          <span class="report-toggle-icon">▼</span>
        </div>
        <div class="report-card-body">
          <p class="report-summary" style="color:var(--red)">${esc(r.error)}</p>
        </div>`;
    } else {
      const isPassed  = r.verdict === 'PASSED';
      const conflicts = r.conflicts || [];
      const notes     = r.notes     || [];
      const cls       = isPassed ? 'passed' : 'flagged';

      card.className = `report-card ${cls}`;
      card.innerHTML = `
        <div class="report-card-header" onclick="toggleCard(this)">
          <span class="report-filename">${esc(r.filename)}</span>
          <span class="report-verdict-badge ${cls}">${r.verdict}</span>
          <span class="report-toggle-icon">▼</span>
        </div>
        <div class="report-card-body">
          <p class="report-summary">${esc(r.summary)}</p>
          ${conflicts.length > 0 ? `
            <div class="report-items-heading critical">⚠ CRITICAL CONFLICTS — Manual Review Required</div>
            <div class="report-items">${conflicts.map(makeItem).join('')}</div>` : ''}
          ${notes.length > 0 ? `
            <div class="report-items-heading info">ℹ INFORMATIONAL NOTES</div>
            <div class="report-items">${notes.map(makeItem).join('')}</div>` : ''}
        </div>`;
    }

    list.appendChild(card);
  });

  document.getElementById('reportsSection').classList.add('visible');
  document.getElementById('reportsSection').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function toggleCard(header) {
  const card = header.closest('.report-card');
  card.classList.toggle('open');
}

function makeItem(entry) {
  return `<div class="report-item">
    <div class="report-item-field">${esc(entry.field.replace(/_/g,' ').toUpperCase())}</div>
    <div class="report-item-row">
      <div class="report-item-key">TENDER</div>
      <div class="report-item-val">${esc(entry.tender)}</div>
    </div>
    <div class="report-item-row">
      <div class="report-item-key">BIDDER</div>
      <div class="report-item-val">${esc(entry.bidder)}</div>
    </div>
    <div class="report-item-reason">${esc(entry.reason)}</div>
  </div>`;
}


// ── RESET ────────────────────────────────────────────────────────
document.getElementById('resetBtn').addEventListener('click', () => {
  tenderFile  = null;
  bidderFiles = [];

  document.getElementById('fileA').value = '';
  document.getElementById('nameA').textContent = 'No document selected';
  document.getElementById('statusA').textContent = '● Pending';
  document.getElementById('statusA').className = 'zone-status pending';
  document.getElementById('cardA').classList.remove('has-file');

  document.getElementById('nameB').textContent = 'No documents selected';
  document.getElementById('statusB').textContent = '● Pending';
  document.getElementById('statusB').className = 'zone-status pending';
  document.getElementById('cardB').classList.remove('has-file');
  document.getElementById('bidderFileList').innerHTML = '';

  document.getElementById('reportsSection').classList.remove('visible');
  window.scrollTo({ top: 0, behavior: 'smooth' });
});


// ── HELPERS ──────────────────────────────────────────────────────
function esc(str) {
  return String(str ?? '—')
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}