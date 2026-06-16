# Agent Diary v2 — Tauri Desktop Client

## Architecture

```
┌────────── SERVER ──────────┐     ┌────────── CLIENT ──────────┐
│ Where Hermes runs          │     │ Where the user sits        │
│                            │     │                            │
│ Python agent-diary server  │◄────│ Tauri desktop app          │
│ port 8041                  │HTTP │ native window, no browser  │
│ SQLite DB + file storage   │     │ connects to server URL     │
│ Hermes import pipeline     │     │ zero backend dependencies  │
│                            │     │                            │
│ One per deployment         │     │ One per user's machine     │
└────────────────────────────┘     └────────────────────────────┘
```

### Server (exists today, runs on Emily)

- `agent-diary serve --host 0.0.0.0 --port 8041`
- All POST API endpoints (list_entries, search, imports, overlays, etc.)
- SQLite database + file storage
- Cron job imports Hermes sessions

### Client (what we build)

- Tauri v2 desktop app
- Wraps the existing UI (`index.html`, `app.js`, `styles.css`) in a native webview window
- User enters the server URL once (saved to app config)
- No Python, no server, no database — pure frontend
- Platform packages: .dmg (Mac), .msi (Windows), .AppImage (Linux)

## Client Project Structure

```
agent-diary/
├── ui/                            # Frontend sources (existing)
│   ├── index.html
│   ├── app.js
│   └── styles.css
├── src-tauri/                     # NEW — Tauri client app
│   ├── src/
│   │   ├── main.rs                # App entry, window creation, menu
│   │   ├── settings.rs            # Server URL persistence
│   │   └── lib.rs                 # Tauri builder setup
│   ├── icons/                     # App icons for each platform
│   ├── Cargo.toml
│   ├── tauri.conf.json            # Window config, app metadata
│   ├── capabilities/
│   │   └── default.json           # Tauri v2 capability permissions
│   └── build.rs                  # Build script
├── package.json                   # Tauri tooling deps (npm)
├── pyproject.toml                 # Unchanged (server-side)
└── README.md                      # Updated with client build instructions
```

## Migration Plan for app.js

The current `app.js` talks to the API via one function:

```js
async function post(path, payload) {
  const response = await fetch(`${state.apiBase}${path}`, { method: "POST", ... })
  return response.json()
}
```

In the Tauri client, this **barely changes**. We replace the hardcoded `apiBase` with a stored server URL and add connection-status awareness:

```js
// Store server URL in app config, settable from the UI
// Then same fetch() call as before, just to the configured remote
async function post(path, payload) {
  const url = `${await getServerUrl()}${path}`
  ...
}
```

95% of `app.js` stays untouched. The only additions:
- Settings view (server URL input + test connection button)
- Connection status indicator (green/grey dot)
- Error state (what happens when server is unreachable)

## Build & Distribution

```bash
# Development
cd agent-diary
npm install
npm run tauri dev

# Ship it
npm run tauri build
# → src-tauri/target/release/bundle/
#     agent-diary_x.y.z_x64.dmg        (Mac)
#     agent-diary_x.y.z_x64.msi       (Windows)
#     agent-diary_x.y.z_x86_64.AppImage (Linux)
```

## GitHub Release Workflow

1. Tag a release → GitHub Actions builds for all 3 platforms
2. Uploads `.dmg`, `.msi`, `.AppImage` to the release page
3. User downloads the right one for their OS, opens it, enters server URL

## Build Size Estimate

- Tauri base: ~5MB per binary
- Total install: ~10-15MB
- Vs. Electron: would be ~150MB+