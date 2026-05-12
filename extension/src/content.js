/**
 * content.js — Injected into every page.
 *
 * Features:
 *   1. Toast notifications when watchlist add succeeds/fails
 *   2. Sidebar panel (opens on demand from popup or keyboard shortcut)
 *      showing stories from the archive relevant to the current page
 */

// ── Toast notifications ────────────────────────────────────────────────────────

function showToast(message, type = "success") {
  const existing = document.getElementById("fti-toast");
  if (existing) existing.remove();

  const toast = document.createElement("div");
  toast.id = "fti-toast";
  toast.className = `fti-toast fti-toast-${type}`;
  toast.innerHTML = `
    <span class="fti-toast-icon">${type === "success" ? "✅" : "❌"}</span>
    <span>${message}</span>
  `;
  document.body.appendChild(toast);

  // Animate in
  requestAnimationFrame(() => toast.classList.add("fti-toast-visible"));

  // Auto-dismiss
  setTimeout(() => {
    toast.classList.remove("fti-toast-visible");
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

// ── Sidebar panel ─────────────────────────────────────────────────────────────

let sidebarOpen = false;

function createSidebar() {
  if (document.getElementById("fti-sidebar")) return;

  const sidebar = document.createElement("div");
  sidebar.id = "fti-sidebar";
  sidebar.className = "fti-sidebar";
  sidebar.innerHTML = `
    <div class="fti-sidebar-header">
      <div class="fti-sidebar-logo">
        <span class="fti-logo-icon">🏦</span>
        <div>
          <div class="fti-logo-title">FinTech Intelligence</div>
          <div class="fti-logo-sub">Related stories</div>
        </div>
      </div>
      <button class="fti-close-btn" id="fti-close">✕</button>
    </div>

    <div class="fti-sidebar-search">
      <input type="text" id="fti-query" class="fti-input"
        placeholder="Ask about this page or search stories…">
      <button class="fti-ask-btn" id="fti-ask">Ask</button>
    </div>

    <div id="fti-results" class="fti-results">
      <div class="fti-loading" id="fti-loading" style="display:none">
        <div class="fti-spinner"></div>
        <span>Searching your archive…</span>
      </div>
      <div id="fti-stories-list"></div>
    </div>

    <div class="fti-sidebar-footer">
      <a id="fti-open-dashboard" href="#" class="fti-footer-link">
        Open Dashboard →
      </a>
    </div>
  `;

  document.body.appendChild(sidebar);

  // Close button
  document.getElementById("fti-close").addEventListener("click", closeSidebar);

  // Ask button
  document.getElementById("fti-ask").addEventListener("click", handleAsk);
  document.getElementById("fti-query").addEventListener("keydown", (e) => {
    if (e.key === "Enter") handleAsk();
  });

  // Dashboard link
  chrome.runtime.sendMessage({ type: "GET_API_URL" }, (res) => {
    document.getElementById("fti-open-dashboard").href = `${res.url}/dashboard`;
    document.getElementById("fti-open-dashboard").target = "_blank";
  });
}

function openSidebar() {
  createSidebar();
  const sidebar = document.getElementById("fti-sidebar");
  sidebar.classList.add("fti-sidebar-open");
  sidebarOpen = true;

  // Auto-search using page title as query
  const pageTitle = document.title.split(/[-|·—]/)[0].trim();
  if (pageTitle) {
    const input = document.getElementById("fti-query");
    input.value = pageTitle;
    handleAsk();
  }
}

function closeSidebar() {
  const sidebar = document.getElementById("fti-sidebar");
  if (sidebar) {
    sidebar.classList.remove("fti-sidebar-open");
    sidebarOpen = false;
  }
}

async function handleAsk() {
  const query = document.getElementById("fti-query").value.trim();
  if (!query) return;

  const loading = document.getElementById("fti-loading");
  const list = document.getElementById("fti-stories-list");

  loading.style.display = "flex";
  list.innerHTML = "";

  try {
    const response = await chrome.runtime.sendMessage({
      type: "API_CALL",
      path: "/chat",
      method: "POST",
      body: { query, user_id: 1, lookback_days: 14 },
    });

    loading.style.display = "none";

    if (!response.ok) {
      list.innerHTML = `<div class="fti-error">❌ ${response.error}</div>`;
      return;
    }

    const { answer, sources } = response.data;

    // Answer block
    list.innerHTML = `
      <div class="fti-answer">${answer.replace(/\n/g, "<br>")}</div>
    `;

    // Source stories
    if (sources && sources.length > 0) {
      const sourcesHtml = sources.map((s) => `
        <a href="${s.url}" target="_blank" class="fti-story-card">
          <div class="fti-story-source">${s.source}</div>
          <div class="fti-story-title">${s.title}</div>
        </a>
      `).join("");

      list.innerHTML += `
        <div class="fti-sources-label">Sources from your archive</div>
        <div class="fti-stories">${sourcesHtml}</div>
      `;
    }
  } catch (e) {
    loading.style.display = "none";
    list.innerHTML = `<div class="fti-error">❌ Could not connect to FinTech Intelligence. Check your settings.</div>`;
  }
}

// ── Message listener ──────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message) => {
  if (message.type === "WATCHLIST_ADDED") {
    showToast(`"${message.entity}" added to your watchlist`);
  }
  if (message.type === "WATCHLIST_ERROR") {
    showToast(`Failed to add to watchlist: ${message.error}`, "error");
  }
  if (message.type === "OPEN_SIDEBAR") {
    if (sidebarOpen) {
      closeSidebar();
    } else {
      openSidebar();
    }
  }
  if (message.type === "PREFILL_QUERY" && message.query) {
    openSidebar();
    setTimeout(() => {
      const input = document.getElementById("fti-query");
      if (input) {
        input.value = message.query;
        handleAsk();
      }
    }, 100);
  }
});