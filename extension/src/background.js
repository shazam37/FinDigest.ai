/**
 * background.js — Service worker for FinTech Intelligence extension.
 *
 * Responsibilities:
 *   1. Right-click context menu: "Add to FinTech Watchlist"
 *   2. API calls to the backend (avoids CORS issues from content scripts)
 *   3. Badge updates showing unread alerts
 */

const DEFAULT_API_URL = "http://localhost:8000";

// ── Helpers ───────────────────────────────────────────────────────────────────

async function getApiUrl() {
  const result = await chrome.storage.sync.get(["apiUrl"]);
  return result.apiUrl || DEFAULT_API_URL;
}

async function apiCall(path, method = "GET", body = null) {
  const base = await getApiUrl();
  const opts = {
    method,
    headers: { "Content-Type": "application/json" },
  };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(`${base}${path}`, opts);
  if (!res.ok) throw new Error(`API error ${res.status}`);
  return res.json();
}

// ── Context menu ──────────────────────────────────────────────────────────────

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "addToWatchlist",
    title: "📊 Add \"%s\" to FinTech Watchlist",
    contexts: ["selection"],
  });

  chrome.contextMenus.create({
    id: "watchlistPage",
    title: "📊 Add this company to FinTech Watchlist",
    contexts: ["page"],
  });

  chrome.contextMenus.create({
    id: "askAboutPage",
    title: "🔍 Ask FinTech Intelligence about this page",
    contexts: ["page"],
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === "addToWatchlist" && info.selectionText) {
    await handleAddToWatchlist(info.selectionText.trim(), tab);
  } else if (info.menuItemId === "watchlistPage") {
    // Try to extract company name from page title
    const title = tab.title || "";
    const entity = title.split(/[-|·—]/)[0].trim();
    await handleAddToWatchlist(entity, tab);
  } else if (info.menuItemId === "askAboutPage") {
    // Open popup and pre-fill with page context
    chrome.storage.session.set({ pendingPageUrl: tab.url, pendingPageTitle: tab.title });
    chrome.action.openPopup();
  }
});

async function handleAddToWatchlist(entity, tab) {
  try {
    await apiCall("/watchlist?user_id=1", "POST", {
      entity,
      entity_type: "company",
    });
    // Notify the content script to show a toast
    chrome.tabs.sendMessage(tab.id, {
      type: "WATCHLIST_ADDED",
      entity,
    });
  } catch (e) {
    chrome.tabs.sendMessage(tab.id, {
      type: "WATCHLIST_ERROR",
      error: e.message,
    });
  }
}

// ── Message handler (from popup and content script) ───────────────────────────

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "API_CALL") {
    apiCall(message.path, message.method || "GET", message.body || null)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((e) => sendResponse({ ok: false, error: e.message }));
    return true; // Keep channel open for async response
  }

  if (message.type === "GET_API_URL") {
    getApiUrl().then((url) => sendResponse({ url }));
    return true;
  }
});