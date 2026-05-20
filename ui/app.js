const state = {
  apiBase: "http://127.0.0.1:8041",
  limit: 20,
  offset: 0,
  selectedEntryId: null,
  searchQuery: "",
  selectedSearchHitEntryId: null,
};
const STORAGE_KEY = "agentDiaryUiStateV1";

const apiBaseInput = document.getElementById("apiBase");
const reloadBtn = document.getElementById("reloadBtn");
const prevPageBtn = document.getElementById("prevPageBtn");
const nextPageBtn = document.getElementById("nextPageBtn");
const timelineList = document.getElementById("timelineList");
const timelineStatus = document.getElementById("timelineStatus");
const detailMeta = document.getElementById("detailMeta");
const detailBody = document.getElementById("detailBody");
const detailStatus = document.getElementById("detailStatus");
const artifactList = document.getElementById("artifactList");
const artifactDetails = document.getElementById("artifactDetails");
const searchForm = document.getElementById("searchForm");
const searchInput = document.getElementById("searchInput");
const searchResults = document.getElementById("searchResults");
const searchStatus = document.getElementById("searchStatus");
let isApplyingUrlState = false;

async function post(path, payload) {
  const response = await fetch(`${state.apiBase}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || `HTTP ${response.status}`);
  }
  return data.result || data;
}

function renderTimeline(items) {
  timelineList.setAttribute("aria-busy", "false");
  timelineList.innerHTML = "";
  if (!items.length) {
    timelineList.innerHTML = '<li class="item muted">No entries in this page.</li>';
    return;
  }

  const grouped = groupByDay(items);
  for (const [dayKey, dayItems] of grouped) {
    const headerLi = document.createElement("li");
    headerLi.className = "day-header";
    headerLi.textContent = formatDayHeader(dayKey);
    timelineList.appendChild(headerLi);

    for (const item of dayItems) {
      const li = document.createElement("li");
      li.className = "item";
      li.innerHTML = `
      <button data-entry-id="${item.entry_id}" aria-current="${state.selectedEntryId === item.entry_id ? "true" : "false"}" class="${state.selectedEntryId === item.entry_id ? "active" : ""}">
        <div class="muted">${formatEntryTime(item.created_at)} · ${item.entry_type} · ${item.source} · ${item.author_role}</div>
        <div class="preview">${item.preview}</div>
      </button>
    `;
      li.querySelector("button").addEventListener("click", () => loadEntry(item.entry_id));
      timelineList.appendChild(li);
    }
  }
  wireListKeyboardNav(timelineList);
}

function groupByDay(items) {
  const map = new Map();
  for (const item of items) {
    const key = normalizeDayKey(item.created_at);
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(item);
  }
  return map;
}

function normalizeDayKey(iso) {
  const date = new Date(iso);
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function formatDayHeader(dayKey) {
  const day = new Date(`${dayKey}T00:00:00`);
  const todayKey = normalizeDayKey(new Date().toISOString());
  const yesterdayDate = new Date();
  yesterdayDate.setDate(yesterdayDate.getDate() - 1);
  const yesterdayKey = normalizeDayKey(yesterdayDate.toISOString());

  const base = day.toLocaleDateString(undefined, {
    weekday: "long",
    month: "short",
    day: "numeric",
    year: "numeric",
  });
  if (dayKey === todayKey) return `Today · ${base}`;
  if (dayKey === yesterdayKey) return `Yesterday · ${base}`;
  return base;
}

function formatEntryTime(iso) {
  const date = new Date(iso);
  const human = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return `${human} (${iso})`;
}

function formatMetaDateTime(iso) {
  const date = new Date(iso);
  return `${date.toLocaleString()} · ${iso}`;
}

function renderDetail(detail) {
  const raw = detail.raw_entry;
  detailMeta.innerHTML = "";
  for (const text of [formatMetaDateTime(raw.created_at), raw.entry_type, raw.source, raw.author_role]) {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = text || "";
    detailMeta.appendChild(chip);
  }

  detailBody.textContent = raw.content || "";
  detailStatus.textContent = `Viewing ${raw.entry_id}`;
  detailBody.setAttribute("aria-label", `Diary entry ${raw.entry_id}`);

  artifactList.innerHTML = "";
  if (!detail.artifacts?.length) {
    artifactList.innerHTML = '<li class="item muted">No artifacts attached.</li>';
  }
  for (const artifact of detail.artifacts || []) {
    const li = document.createElement("li");
    li.className = "item";
    let openLoopHtml = "";
    if (artifact.artifact_type === "analysis:open-loop") {
      const loops = Array.isArray(artifact.open_loops) ? artifact.open_loops : [];
      openLoopHtml = `
        <div class="derived-badge">Derived Interpretation</div>
        <div class="muted">Open loops: ${loops.length}</div>
        <ul class="loop-list">
          ${loops
            .map((loop) => {
              const strength = loop?.signals?.strength || "unknown";
              const confidence =
                typeof loop?.signals?.confidence === "number"
                  ? ` (${Math.round(loop.signals.confidence * 100)}%)`
                  : "";
              const links = Array.isArray(loop.supporting_entry_ids)
                ? loop.supporting_entry_ids
                    .map(
                      (id) =>
                        `<button class="support-link" type="button" data-support-entry-id="${id}">${id}</button>`
                    )
                    .join(" ")
                : "";
              return `
                <li class="loop-item">
                  <div><strong>${loop.title || "Open loop"}</strong></div>
                  <div class="muted">${loop.summary || ""}</div>
                  <div class="muted">strength: ${strength}${confidence}</div>
                  <div class="muted">supporting entries:</div>
                  <div class="support-links">${links || '<span class="muted">none</span>'}</div>
                </li>
              `;
            })
            .join("")}
        </ul>
      `;
    }
    li.innerHTML = `
      <div><strong>${artifact.artifact_type || "artifact"}</strong></div>
      <div class="muted">${formatMetaDateTime(artifact.created_at || "")}</div>
      <div class="muted">producer: ${artifact.producer || ""}</div>
      <div class="muted">id: ${artifact.artifact_id || ""}</div>
      ${openLoopHtml}
    `;
    for (const btn of li.querySelectorAll("button[data-support-entry-id]")) {
      btn.addEventListener("click", async () => {
        const id = btn.getAttribute("data-support-entry-id");
        if (!id) return;
        await loadEntry(id);
      });
    }
    artifactList.appendChild(li);
  }
}

function renderSearchResults(matches) {
  searchResults.setAttribute("aria-busy", "false");
  searchResults.innerHTML = "";
  if (!matches.length) {
    searchResults.innerHTML = '<li class="item muted">No memory hits for this query.</li>';
    return;
  }
  for (const hit of matches) {
    const li = document.createElement("li");
    li.className = "item";
    li.innerHTML = `
      <button data-entry-id="${hit.entry_id}" aria-current="${state.selectedSearchHitEntryId === hit.entry_id ? "true" : "false"}" class="${state.selectedSearchHitEntryId === hit.entry_id ? "active" : ""}">
        <div class="muted">${formatMetaDateTime(hit.indexed_at)} · artifact ${hit.artifact_id}</div>
        <div class="preview">${hit.match_text}</div>
      </button>
    `;
    li.querySelector("button").addEventListener("click", async () => {
      state.selectedSearchHitEntryId = hit.entry_id;
      persistState();
      await loadEntry(hit.entry_id);
    });
    searchResults.appendChild(li);
  }
  wireListKeyboardNav(searchResults);
}

function showError(listEl, message) {
  listEl.setAttribute("aria-busy", "false");
  listEl.innerHTML = `<li class="item error">${message}</li>`;
}

function wireListKeyboardNav(listEl) {
  const buttons = Array.from(listEl.querySelectorAll("button[data-entry-id]"));
  for (const btn of buttons) {
    btn.addEventListener("keydown", (event) => {
      const currentIndex = buttons.indexOf(btn);
      if (currentIndex === -1) return;
      if (event.key === "ArrowDown") {
        event.preventDefault();
        const next = buttons[Math.min(buttons.length - 1, currentIndex + 1)];
        next.focus();
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        const prev = buttons[Math.max(0, currentIndex - 1)];
        prev.focus();
      } else if (event.key === "Home") {
        event.preventDefault();
        buttons[0].focus();
      } else if (event.key === "End") {
        event.preventDefault();
        buttons[buttons.length - 1].focus();
      }
    });
  }
}

async function loadTimeline() {
  timelineStatus.textContent = "Loading entries...";
  timelineList.setAttribute("aria-busy", "true");
  try {
    const result = await post("/list_entries", { limit: state.limit, offset: state.offset });
    renderTimeline(result.items || []);
    timelineStatus.textContent = `Showing ${result.items.length} entries · offset ${state.offset}`;
  } catch (err) {
    showError(timelineList, `Timeline error: ${err.message}`);
    timelineStatus.textContent = "Could not load entries.";
  }
}

async function loadEntry(entryId) {
  detailStatus.textContent = "Loading entry...";
  try {
    const detail = await post("/fetch_entry_detail", { entry_id: entryId });
    state.selectedEntryId = entryId;
    persistState();
    writeUrlState();
    renderDetail(detail);
    detailBody.focus();
    await loadTimeline();
  } catch (err) {
    detailBody.textContent = `Entry load error: ${err.message}`;
    detailStatus.textContent = "Could not load entry.";
  }
}

async function runSearch(query) {
  searchStatus.textContent = "Searching compressed memory...";
  searchResults.setAttribute("aria-busy", "true");
  try {
    const result = await post("/search_memory", { query, limit: 20, filters: {} });
    state.searchQuery = query;
    persistState();
    writeUrlState();
    renderSearchResults(result.matches || []);
    searchStatus.textContent = `Found ${(result.matches || []).length} memory hits.`;
  } catch (err) {
    showError(searchResults, `Search error: ${err.message}`);
    searchStatus.textContent = "Search failed.";
  }
}

function persistState() {
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({
      apiBase: state.apiBase,
      limit: state.limit,
      offset: state.offset,
      selectedEntryId: state.selectedEntryId,
      searchQuery: state.searchQuery,
      selectedSearchHitEntryId: state.selectedSearchHitEntryId,
    })
  );
}

function writeUrlState() {
  if (isApplyingUrlState) return;
  const params = new URLSearchParams(window.location.search);
  if (state.selectedEntryId) {
    params.set("entry", state.selectedEntryId);
  } else {
    params.delete("entry");
  }
  if (state.searchQuery) {
    params.set("q", state.searchQuery);
  } else {
    params.delete("q");
  }
  if (state.offset > 0) {
    params.set("offset", String(state.offset));
  } else {
    params.delete("offset");
  }
  const next = `${window.location.pathname}${params.toString() ? `?${params.toString()}` : ""}`;
  window.history.replaceState({}, "", next);
}

function restoreStateFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const entry = params.get("entry");
  const q = params.get("q");
  const offset = params.get("offset");
  let found = false;
  if (entry) {
    state.selectedEntryId = entry;
    found = true;
  }
  if (q) {
    state.searchQuery = q;
    found = true;
  }
  if (offset !== null) {
    const parsed = Number.parseInt(offset, 10);
    if (Number.isFinite(parsed) && parsed >= 0) {
      state.offset = parsed;
      found = true;
    }
  }
  return found;
}

function restoreState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    state.apiBase = parsed.apiBase || state.apiBase;
    state.limit = Number.isInteger(parsed.limit) ? parsed.limit : state.limit;
    state.offset = Number.isInteger(parsed.offset) ? parsed.offset : state.offset;
    state.selectedEntryId = parsed.selectedEntryId || null;
    state.searchQuery = parsed.searchQuery || "";
    state.selectedSearchHitEntryId = parsed.selectedSearchHitEntryId || null;
  } catch (_err) {
    // Ignore malformed local state and continue with defaults.
  }
}

reloadBtn.addEventListener("click", async () => {
  state.apiBase = apiBaseInput.value.trim().replace(/\/$/, "");
  persistState();
  writeUrlState();
  await loadTimeline();
});

prevPageBtn.addEventListener("click", async () => {
  state.offset = Math.max(0, state.offset - state.limit);
  persistState();
  writeUrlState();
  await loadTimeline();
});

nextPageBtn.addEventListener("click", async () => {
  state.offset += state.limit;
  persistState();
  writeUrlState();
  await loadTimeline();
});

searchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = searchInput.value.trim();
  if (!query) return;
  await runSearch(query);
});

async function init() {
  const hasUrlState = restoreStateFromUrl();
  if (!hasUrlState) {
    restoreState();
  }
  apiBaseInput.value = state.apiBase;
  searchInput.value = state.searchQuery;
  state.apiBase = apiBaseInput.value.trim().replace(/\/$/, "");
  await loadTimeline();
  if (state.searchQuery) {
    await runSearch(state.searchQuery);
  } else {
    searchStatus.textContent = "Search artifacts to jump to raw entries.";
  }
  if (state.selectedEntryId) {
    await loadEntry(state.selectedEntryId);
  } else {
    detailStatus.textContent = "Select an entry from timeline or search.";
    artifactDetails.open = false;
  }
  writeUrlState();
}

window.addEventListener("popstate", async () => {
  isApplyingUrlState = true;
  const snapshot = {
    selectedEntryId: state.selectedEntryId,
    searchQuery: state.searchQuery,
    offset: state.offset,
  };
  state.selectedEntryId = null;
  state.searchQuery = "";
  state.offset = 0;
  const hasUrlState = restoreStateFromUrl();
  if (!hasUrlState) {
    state.selectedEntryId = snapshot.selectedEntryId;
    state.searchQuery = snapshot.searchQuery;
    state.offset = snapshot.offset;
  }
  searchInput.value = state.searchQuery;
  await loadTimeline();
  if (state.searchQuery) {
    await runSearch(state.searchQuery);
  } else {
    searchResults.innerHTML = "";
    searchStatus.textContent = "Search artifacts to jump to raw entries.";
  }
  if (state.selectedEntryId) {
    await loadEntry(state.selectedEntryId);
  } else {
    detailMeta.innerHTML = "";
    detailBody.textContent = "Select an entry to view raw detail.";
    detailStatus.textContent = "Select an entry from timeline or search.";
    artifactList.innerHTML = "";
  }
  isApplyingUrlState = false;
});

init();
