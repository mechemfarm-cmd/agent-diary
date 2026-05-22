const state = {
  apiBase: "http://127.0.0.1:8041",
  limit: 100,
  offset: 0,
  selectedEntryId: null,
  searchQuery: "",
  selectedSearchHitEntryId: null,
};
const STORAGE_KEY = "agentDiaryUiStateV2";

const apiBaseInput = document.getElementById("apiBase");
const reloadBtn = document.getElementById("reloadBtn");
const prevPageBtn = document.getElementById("prevPageBtn");
const nextPageBtn = document.getElementById("nextPageBtn");
const timelineList = document.getElementById("timelineList");
const timelineStatus = document.getElementById("timelineStatus");
const detailMeta = document.getElementById("detailMeta");
const detailBody = document.getElementById("detailBody");
const detailStatus = document.getElementById("detailStatus");
const briefDetails = document.getElementById("briefDetails");
const briefBody = document.getElementById("briefBody");
const memoryDetails = document.getElementById("memoryDetails");
const memoryArtifactList = document.getElementById("memoryArtifactList");
const artifactList = document.getElementById("artifactList");
const artifactDetails = document.getElementById("artifactDetails");
const searchForm = document.getElementById("searchForm");
const searchInput = document.getElementById("searchInput");
const searchResults = document.getElementById("searchResults");
const searchStatus = document.getElementById("searchStatus");
let isApplyingUrlState = false;
let selectedTimelineContext = null;

const SPEAKER_TONES = [
  {
    accent: "#2f5d78",
    surface: "#eaf3f8",
    ink: "#123041",
    border: "#b8cede",
  },
  {
    accent: "#7a4f1d",
    surface: "#f6ead8",
    ink: "#4a3016",
    border: "#dcb98a",
  },
  {
    accent: "#4f6d2d",
    surface: "#edf4e3",
    ink: "#2a4017",
    border: "#bfd09f",
  },
  {
    accent: "#6b467d",
    surface: "#f1e8f7",
    ink: "#382246",
    border: "#d3bedf",
  },
  {
    accent: "#8b3f59",
    surface: "#f8e9ef",
    ink: "#4d2130",
    border: "#e0b7c6",
  },
  {
    accent: "#2f6d68",
    surface: "#e8f4f2",
    ink: "#153935",
    border: "#b4d6d1",
  },
];

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
      timelineList.appendChild(buildTimelineItem(item));
    }
  }

  if (
    selectedTimelineContext &&
    state.selectedEntryId === selectedTimelineContext.entry_id &&
    !items.some((item) => item.entry_id === state.selectedEntryId)
  ) {
    const headerLi = document.createElement("li");
    headerLi.className = "day-header";
    headerLi.textContent = "Selected Entry";
    timelineList.prepend(buildTimelineItem(selectedTimelineContext));
    timelineList.prepend(headerLi);
  }
  wireListKeyboardNav(timelineList);
}

function buildTimelineItem(item) {
  const li = document.createElement("li");
  li.className = "item";
  const briefHtml = item.brief ? `<div class="brief">${item.brief}</div>` : "";
  li.innerHTML = `
    <button data-entry-id="${item.entry_id}" aria-current="${state.selectedEntryId === item.entry_id ? "true" : "false"}" class="${state.selectedEntryId === item.entry_id ? "active" : ""}">
      <div class="muted">${formatEntryTime(item.created_at)} · ${item.entry_type} · ${item.source} · ${item.author_role}</div>
      ${briefHtml}
      <div class="preview">${item.preview}</div>
    </button>
  `;
  li.querySelector("button").addEventListener("click", () => loadEntry(item.entry_id));
  return li;
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

function normalizeSpeakerLabel(label) {
  return String(label || "")
    .trim()
    .replace(/\s+/g, " ");
}

function speakerTone(label) {
  const normalized = normalizeSpeakerLabel(label).toLowerCase();
  if (!normalized) {
    return SPEAKER_TONES[0];
  }
  if (["user", "human", "you", "bill", "willard", "willardmechem"].includes(normalized)) {
    return SPEAKER_TONES[0];
  }
  if (["assistant", "agent", "tom", "codex", "bot"].includes(normalized)) {
    return SPEAKER_TONES[1];
  }
  let hash = 0;
  for (let index = 0; index < normalized.length; index += 1) {
    hash = (hash * 31 + normalized.charCodeAt(index)) >>> 0;
  }
  return SPEAKER_TONES[hash % SPEAKER_TONES.length];
}

function parseDialogueTurns(content) {
  if (typeof content !== "string" || !content.trim()) {
    return [];
  }

  const turns = [];
  let current = null;
  for (const line of content.replace(/\r\n/g, "\n").split("\n")) {
    const match = line.match(/^([A-Za-z][A-Za-z0-9._/-]{0,40}):\s*(.*)$/);
    if (match) {
      if (current) {
        turns.push(current);
      }
      current = {
        speaker: normalizeSpeakerLabel(match[1]),
        body: match[2],
      };
      continue;
    }
    if (!current) {
      current = { speaker: "", body: line };
      continue;
    }
    current.body = current.body ? `${current.body}\n${line}` : line;
  }
  if (current) {
    turns.push(current);
  }
  return turns.filter((turn) => turn.body.trim() || turn.speaker.trim());
}

function clearDetailBody() {
  detailBody.classList.remove("dialogue-view");
  detailBody.innerHTML = "";
}

function renderDialogueBody(raw, turns) {
  detailBody.classList.add("dialogue-view");
  detailBody.innerHTML = "";

  const transcript = document.createElement("div");
  transcript.className = "dialogue-transcript";

  const note = document.createElement("div");
  note.className = "dialogue-note muted";
  note.textContent = "Speaker-separated raw entry view. The stored raw content remains the source of truth.";
  transcript.appendChild(note);

  const renderedTurns = turns.length ? turns : [{ speaker: raw.speaker || "", body: raw.content || "" }];
  for (const turn of renderedTurns) {
    const speakerLabel = normalizeSpeakerLabel(turn.speaker) || "Speaker";
    const tone = speakerTone(speakerLabel);
    const card = document.createElement("article");
    card.className = "dialogue-turn";
    card.style.setProperty("--turn-accent", tone.accent);
    card.style.setProperty("--turn-surface", tone.surface);
    card.style.setProperty("--turn-ink", tone.ink);
    card.style.setProperty("--turn-border", tone.border);

    const header = document.createElement("div");
    header.className = "dialogue-turn-header";

    const speaker = document.createElement("span");
    speaker.className = "dialogue-speaker";
    speaker.textContent = speakerLabel;

    const body = document.createElement("div");
    body.className = "dialogue-turn-body";
    body.textContent = turn.body || "";

    header.appendChild(speaker);
    card.appendChild(header);
    card.appendChild(body);
    transcript.appendChild(card);
  }

  detailBody.appendChild(transcript);
}

function renderDetail(detail) {
  const raw = detail.raw_entry;
  const artifacts = Array.isArray(detail.artifacts) ? detail.artifacts : [];
  const memoryArtifacts = artifacts.filter((artifact) =>
    ["memory", "compressed-memory"].includes(artifact.artifact_type)
  );
  const briefArtifacts = artifacts.filter((artifact) => artifact.artifact_type === "conversation-brief");
  const secondaryArtifacts = artifacts.filter(
    (artifact) => !["memory", "compressed-memory", "conversation-brief"].includes(artifact.artifact_type)
  );
  detailMeta.innerHTML = "";
  for (const text of [formatMetaDateTime(raw.created_at), raw.entry_type, raw.source, raw.author_role]) {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = text || "";
    detailMeta.appendChild(chip);
  }

  const content = raw.content || "";
  const turns = raw.entry_type === "chat_log" && raw.author_role === "mixed" ? parseDialogueTurns(content) : [];
  if (turns.length) {
    renderDialogueBody(raw, turns);
  } else {
    clearDetailBody();
    detailBody.textContent = content;
  }
  detailStatus.textContent = `Viewing ${raw.entry_id}`;
  detailBody.setAttribute("aria-label", `Diary entry ${raw.entry_id}`);

  if (briefArtifacts.length) {
    briefBody.textContent = briefArtifacts[0].content || "";
    briefDetails.open = true;
  } else {
    briefBody.textContent = "No conversation brief is attached to this entry yet.";
    briefDetails.open = false;
  }

  memoryArtifactList.innerHTML = "";
  if (!memoryArtifacts.length) {
    memoryArtifactList.innerHTML =
      '<li class="item muted">No compressed-memory artifact is attached to this entry yet.</li>';
  }
  for (const artifact of memoryArtifacts) {
    const li = document.createElement("li");
    li.className = "item";
    li.innerHTML = `
      <div><strong>${artifact.artifact_type || "compressed-memory"}</strong></div>
      <div class="muted">${formatMetaDateTime(artifact.created_at || "")}</div>
      <div class="muted">producer: ${artifact.producer || ""}</div>
      <pre class="artifact-body">${artifact.content || ""}</pre>
    `;
    memoryArtifactList.appendChild(li);
  }
  memoryDetails.hidden = true;
  memoryDetails.open = false;

  artifactList.innerHTML = "";
  if (!secondaryArtifacts.length) {
    artifactList.innerHTML = '<li class="item muted">No artifacts attached.</li>';
  }
  for (const artifact of secondaryArtifacts) {
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
  artifactDetails.open = secondaryArtifacts.length > 0;
}

function summarizePreview(text, size = 140) {
  const compact = String(text || "").replace(/\s+/g, " ").trim();
  if (compact.length <= size) {
    return compact;
  }
  return `${compact.slice(0, size - 3)}...`;
}

function renderSearchResults(matches) {
  searchResults.setAttribute("aria-busy", "false");
  searchResults.innerHTML = "";
  if (!matches.length) {
    searchResults.innerHTML = '<li class="item muted">No memory hits for this query.</li>';
    return;
  }
  for (const hit of matches) {
    const layerLabel =
      hit.match_layer === "compressed_memory" ? "compressed memory" : "raw entry fallback";
    const li = document.createElement("li");
    li.className = "item";
    li.innerHTML = `
      <button data-entry-id="${hit.entry_id}" aria-current="${state.selectedSearchHitEntryId === hit.entry_id ? "true" : "false"}" class="${state.selectedSearchHitEntryId === hit.entry_id ? "active" : ""}">
        <div class="muted">${formatMetaDateTime(hit.indexed_at)} · ${layerLabel}${hit.artifact_id ? ` · artifact ${hit.artifact_id}` : ""}</div>
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
    selectedTimelineContext = {
      entry_id: detail.raw_entry.entry_id,
      created_at: detail.raw_entry.created_at,
      entry_type: detail.raw_entry.entry_type,
      source: detail.raw_entry.source,
      author_role: detail.raw_entry.author_role,
      preview: summarizePreview(detail.raw_entry.content),
    };
    persistState();
    writeUrlState();
    renderDetail(detail);
    await loadTimeline();
  } catch (err) {
    detailBody.textContent = `Entry load error: ${err.message}`;
    detailStatus.textContent = "Could not load entry.";
  }
}

async function runSearch(query) {
  searchStatus.textContent = "Searching memory layers...";
  searchResults.setAttribute("aria-busy", "true");
  try {
    const result = await post("/search_memory", { query, limit: 20, filters: {} });
    state.searchQuery = query;
    persistState();
    writeUrlState();
    renderSearchResults(result.matches || []);
    const summary = result.match_summary || {};
    if (summary.using_fallback) {
      searchStatus.textContent = `Found ${(result.matches || []).length} raw-entry fallback hits. Compressed-memory hits: 0.`;
    } else {
      searchStatus.textContent = `Found ${(result.matches || []).length} compressed-memory hits.`;
    }
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
  state.offset = 0;
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
    searchStatus.textContent = "Search prefers compressed memory and falls back to raw entries when needed.";
  }
  if (state.selectedEntryId) {
    await loadEntry(state.selectedEntryId);
  } else {
    detailStatus.textContent = "Select an entry from timeline or search.";
    artifactDetails.open = false;
    memoryDetails.hidden = true;
    memoryDetails.open = false;
    clearDetailBody();
    detailBody.textContent = "Select an entry to view raw detail.";
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
    searchStatus.textContent = "Search prefers compressed memory and falls back to raw entries when needed.";
  }
  if (state.selectedEntryId) {
    await loadEntry(state.selectedEntryId);
  } else {
    detailMeta.innerHTML = "";
    clearDetailBody();
    detailBody.textContent = "Select an entry to view raw detail.";
    detailStatus.textContent = "Select an entry from timeline or search.";
    memoryDetails.hidden = true;
    memoryDetails.open = false;
    memoryArtifactList.innerHTML = "";
    artifactList.innerHTML = "";
  }
  isApplyingUrlState = false;
});

init();
