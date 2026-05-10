# FinTech Intelligence — Browser Extension

A Chrome/Firefox extension that brings your FinTech Intelligence agent into every webpage you visit.

## Features

### Popup (click the extension icon)

| Tab | What it does |
|---|---|
| **Ask** | Ask natural language questions about recent fintech news — answers come from your story archive via RAG |
| **Watchlist** | View, add, and remove watchlist entities with live 7-day sentiment scores |
| **Status** | See last run status, story count, trigger a run, preview last email |
| **Settings** | Set your backend URL and user ID |

### Right-click context menu

- **Select any text** on a page → right-click → "Add to FinTech Watchlist" — adds the selected text as a watched entity in one click
- **On any page** → right-click → "Ask FinTech Intelligence about this page" — opens the popup pre-filled with the page title

### Sidebar panel

Click "Open sidebar" in the popup or trigger it from the context menu to open a persistent sidebar on any page:
- Automatically searches your story archive using the page title as the query
- Shows AI-synthesised answer with citations from your stored stories
- Stays open as you scroll — close with ✕

## Installation

### Step 1: Generate icons

```bash
python scripts/generate_icons.py
```

### Step 2: Set your backend URL

Open `extension/src/popup.html` and note the default URL is `http://localhost:8000`.
You can change it in the extension's Settings tab after loading.

### Step 3: Load in Chrome

1. Open `chrome://extensions`
2. Toggle **Developer mode** ON (top right)
3. Click **Load unpacked**
4. Select the `extension/` folder (the one containing `manifest.json`)
5. Pin the extension to your toolbar

### Step 4: Configure

1. Click the extension icon → **Settings** tab
2. Enter your deployed backend URL: `https://your-app.onrender.com`
3. Click **Save** then **Test Connection**

### Firefox

1. Open `about:debugging`
2. Click **This Firefox → Load Temporary Add-on**
3. Select `extension/manifest.json`

Note: Firefox uses `browser.*` APIs in some contexts but the extension uses `chrome.*` which Firefox supports via its WebExtensions compatibility layer.

## How the sidebar and Q&A work

The extension sends your question to `POST /chat` on your backend. The backend:
1. Embeds your query with the same model used for story storage
2. Searches your pgvector story archive for similar stories (last 14 days)
3. Sends the retrieved stories + your question to Groq for answer synthesis
4. Returns the answer with citations

All data stays within your own backend — the extension makes no third-party API calls.

## Permissions explained

| Permission | Why |
|---|---|
| `storage` | Save your backend URL and user ID settings |
| `activeTab` | Read page title for "Ask about this page" feature |
| `contextMenus` | Right-click "Add to watchlist" |
| `host_permissions: https://*/*` | Allow API calls to your deployed backend |

## Publishing to Chrome Web Store

1. Zip the `extension/` folder: `cd fintech-agent && zip -r extension.zip extension/`
2. Go to [Chrome Web Store Developer Dashboard](https://chrome.google.com/webstore/devconsole)
3. Pay the one-time $5 developer fee
4. Upload the zip and fill in the store listing

For a private/unlisted extension (internal use or demo), you can distribute the zip directly — recipients load it via "Load unpacked" or drag-drop the zip onto `chrome://extensions`.