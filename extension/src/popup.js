/**
 * popup.js — FinTech Intelligence extension popup logic.
 *
 * Tabs: Ask · Watchlist · Status · Settings
 * All API calls go through background.js to avoid CORS issues.
 */

// ── Helpers ───────────────────────────────────────────────────────────────────

async function api(path, method = "GET", body = null) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(
      { type: "API_CALL", path, method, body },
      (res) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
        } else if (!res.ok) {
          reject(new Error(res.error || "API error"));
        } else {
          resolve(res.data);
        }
      }
    );
  });
}

async function getSettings() {
  const r = await chrome.storage.sync.get(["apiUrl", "userId"]);
  return {
    apiUrl: r.apiUrl || "http://localhost:8000",
    userId: r.userId || "1",
  };
}

function show(id) { document.getElementById(id).style.display = ""; }
function hide(id) { document.getElementById(id).style.display = "none"; }
function setText(id, text) { document.getElementById(id).textContent = text; }
function setHtml(id, html) { document.getElementById(id).innerHTML = html; }

// ── Tab switching ─────────────────────────────────────────────────────────────

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach((c) => c.classList.remove("active"));
    tab.classList.add("active");
    document.getElementById(`tab-${tab.dataset.tab}`).classList.add("active");

    if (tab.dataset.tab === "watchlist") loadWatchlist();
    if (tab.dataset.tab === "status") loadStatus();
    if (tab.dataset.tab === "settings") loadSettings();
  });
});

// ── Connection check ──────────────────────────────────────────────────────────

async function checkConnection() {
  try {
    await api("/health");
    document.getElementById("status-dot").classList.remove("offline");
    document.getElementById("status-dot").title = "Connected";
  } catch {
    document.getElementById("status-dot").classList.add("offline");
    document.getElementById("status-dot").title = "Cannot connect to backend";
  }
}

// ── Ask tab ───────────────────────────────────────────────────────────────────

async function handleAsk(query) {
  if (!query.trim()) return;

  hide("answer-box");
  hide("sources-section");
  setText("ask-error", "");
  show("answer-loading");

  try {
    const { userId } = await getSettings();
    const data = await api("/chat", "POST", {
      query: query.trim(),
      user_id: parseInt(userId) || 1,
      lookback_days: 14,
    });

    hide("answer-loading");
    document.getElementById("answer-box").innerHTML =
      data.answer.replace(/\n/g, "<br>");
    show("answer-box");

    if (data.sources && data.sources.length > 0) {
      const html = data.sources
        .slice(0, 4)
        .map(
          (s) =>
            `<a href="${s.url}" target="_blank" class="source-link">
              <span style="color:#c9a96e;font-family:'Courier New',monospace;
                font-size:9px;letter-spacing:1px;text-transform:uppercase;">
                ${s.source}</span><br>${s.title.substring(0, 70)}…
            </a>`
        )
        .join("");
      setHtml("sources-list", html);
      show("sources-section");
    }
  } catch (e) {
    hide("answer-loading");
    setText("ask-error", `❌ ${e.message}`);
  }
}

document.getElementById("ask-btn").addEventListener("click", () => {
  handleAsk(document.getElementById("ask-input").value);
});

document.getElementById("ask-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") handleAsk(document.getElementById("ask-input").value);
});

// Ask about the current page
document.getElementById("ask-page-btn").addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const title = (tab.title || "").split(/[-|·—]/)[0].trim();
  if (title) {
    document.getElementById("ask-input").value = title;
    handleAsk(title);
  }
});

// Open sidebar on current page
document.getElementById("sidebar-btn").addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  chrome.tabs.sendMessage(tab.id, { type: "OPEN_SIDEBAR" });
  window.close();
});

// ── Watchlist tab ─────────────────────────────────────────────────────────────

async function loadWatchlist() {
  const list = document.getElementById("wl-list");
  const { userId } = await getSettings();

  show("wl-loading");
  setText("wl-error", "");
  list.innerHTML = "";

  try {
    const data = await api(`/watchlist?user_id=${userId}`);
    hide("wl-loading");

    if (!data.entities || data.entities.length === 0) {
      list.innerHTML = '<div class="empty">No entities watched yet.<br>Type a company name above to start.</div>';
      return;
    }

    // Fetch sentiment for display
    let sentimentData = {};
    try {
      const sentResp = await api(`/watchlist/sentiment?user_id=${userId}&days=7`);
      sentimentData = sentResp.entities || {};
    } catch { /* non-critical */ }

    list.innerHTML = data.entities
      .map((e) => {
        const sent = sentimentData[e.entity];
        let sentHtml = "";
        if (sent && sent.average_score !== null) {
          const sc = sent.average_score;
          const cls = sc >= 0.2 ? "sent-pos" : sc <= -0.2 ? "sent-neg" : "sent-neu";
          sentHtml = `<span class="wl-sentiment ${cls}">${sc >= 0 ? "+" : ""}${sc.toFixed(2)}</span>`;
        }
        return `
          <div class="wl-item">
            <div>
              <div class="wl-entity">${e.entity}</div>
              <div class="wl-type">${e.entity_type}</div>
            </div>
            <div style="display:flex;align-items:center;">
              ${sentHtml}
              <button class="remove-btn" data-id="${e.id}" data-entity="${e.entity}"
                title="Remove from watchlist">✕</button>
            </div>
          </div>`;
      })
      .join("");

    // Remove buttons
    list.querySelectorAll(".remove-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = btn.dataset.id;
        const entity = btn.dataset.entity;
        try {
          await api(`/watchlist/${id}?user_id=${userId}`, "DELETE");
          btn.closest(".wl-item").remove();
          if (list.children.length === 0) {
            list.innerHTML = '<div class="empty">Watchlist is now empty.</div>';
          }
        } catch (e) {
          setText("wl-error", `❌ Could not remove ${entity}`);
        }
      });
    });
  } catch (e) {
    hide("wl-loading");
    setText("wl-error", `❌ ${e.message}`);
  }
}

document.getElementById("wl-add-btn").addEventListener("click", async () => {
  const input = document.getElementById("wl-input");
  const entity = input.value.trim();
  if (!entity) return;

  const { userId } = await getSettings();
  setText("wl-error", "");

  try {
    await api(`/watchlist?user_id=${userId}`, "POST", {
      entity,
      entity_type: "company",
    });
    input.value = "";
    loadWatchlist();
  } catch (e) {
    setText("wl-error", `❌ ${e.message}`);
  }
});

document.getElementById("wl-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") document.getElementById("wl-add-btn").click();
});

// ── Status tab ────────────────────────────────────────────────────────────────

async function loadStatus() {
  hide("status-content");
  show("status-loading");

  try {
    const [healthData, runsData] = await Promise.all([
      api("/health"),
      api("/runs?limit=5"),
    ]);

    hide("status-loading");
    show("status-content");

    const runs = runsData.runs || [];
    const lastRun = runs[0];

    if (lastRun) {
      const stories = lastRun.stories || 0;
      const status = lastRun.status || "unknown";
      const icon = status === "success" ? "✅" : "❌";

      setText("kpi-stories", stories);
      document.getElementById("kpi-status").textContent = icon;
      document.getElementById("kpi-status").style.fontSize = "28px";

      const ts = lastRun.started_at
        ? new Date(lastRun.started_at).toLocaleString("en-GB", {
            day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
          })
        : "—";
      setText("last-run-text", `Last run: ${ts}`);
    }

    const { apiUrl } = await getSettings();

    document.getElementById("run-now-btn").addEventListener("click", async () => {
      try {
        await api("/run-now");
        setText("last-run-text", "Digest triggered — check back in ~60s");
      } catch (e) {
        setText("last-run-text", `❌ ${e.message}`);
      }
    });

    document.getElementById("preview-btn").addEventListener("click", () => {
      chrome.tabs.create({ url: `${apiUrl}/preview` });
    });

    document.getElementById("dashboard-btn").addEventListener("click", () => {
      chrome.tabs.create({ url: `${apiUrl}/dashboard` });
    });
  } catch (e) {
    hide("status-loading");
    show("status-content");
    setText("last-run-text", `❌ Cannot connect: ${e.message}`);
  }
}

// ── Settings tab ──────────────────────────────────────────────────────────────

async function loadSettings() {
  const { apiUrl, userId } = await getSettings();
  document.getElementById("api-url-input").value = apiUrl;
  document.getElementById("user-id-input").value = userId;
}

document.getElementById("save-settings-btn").addEventListener("click", async () => {
  const apiUrl = document.getElementById("api-url-input").value.trim().replace(/\/$/, "");
  const userId = document.getElementById("user-id-input").value.trim() || "1";

  await chrome.storage.sync.set({ apiUrl, userId });

  const fb = document.getElementById("save-feedback");
  fb.style.display = "block";
  setTimeout(() => (fb.style.display = "none"), 2000);

  checkConnection();
});

document.getElementById("test-conn-btn").addEventListener("click", async () => {
  const result = document.getElementById("conn-result");
  result.textContent = "Testing…";
  result.style.color = "#94a3b8";
  try {
    const data = await api("/health");
    result.textContent = `✅ Connected`;
    result.style.color = "#4ade80";
  } catch (e) {
    result.textContent = `❌ ${e.message}`;
    result.style.color = "#f87171";
  }
});

// ── Init ──────────────────────────────────────────────────────────────────────

checkConnection();

// Pre-fill ask input if coming from context menu "ask about page"
chrome.storage.session.get(["pendingPageTitle"], (result) => {
  if (result.pendingPageTitle) {
    document.getElementById("ask-input").value = result.pendingPageTitle;
    chrome.storage.session.remove(["pendingPageUrl", "pendingPageTitle"]);
  }
});