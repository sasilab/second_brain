// Second Brain — chat capture UI (text + voice + image + link)

const TOKEN_KEY = "second_brain_token";

const $ = (id) => document.getElementById(id);

const els = {
  authScreen: $("auth-screen"),
  authPrompt: $("auth-prompt"),
  authForm:   $("auth-form"),
  authPwd:    $("auth-password"),
  authBtn:    $("auth-submit"),
  authError:  $("auth-error"),
  app:        $("app"),
  messages:   $("messages"),
  input:      $("input"),
  sendBtn:    $("send-btn"),
  attachBtn:  $("attach-btn"),
  micBtn:     $("mic-btn"),
  imageInput: $("image-input"),
  logoutBtn:  $("logout-btn"),
  searchBtn:   $("search-btn"),
  searchOverlay: $("search-overlay"),
  searchClose: $("search-close"),
  searchInput: $("search-input"),
  searchType:  $("search-type"),
  searchSource:$("search-source"),
  searchStatus:$("search-status"),
  searchResults:$("search-results"),
  browseBtn:     $("browse-btn"),
  browseOverlay: $("browse-overlay"),
  browseClose:   $("browse-close"),
  browseType:    $("browse-type"),
  browseSource:  $("browse-source"),
  browseTag:     $("browse-tag"),
  browseReset:   $("browse-reset"),
  browseStatus:  $("browse-status"),
  browseResults: $("browse-results"),
  browseMore:    $("browse-more"),
  importBtn:   $("import-btn"),
  settingsBtn:    $("settings-btn"),
  settingsOverlay:$("settings-overlay"),
  settingsClose:  $("settings-close"),
  settingsForm:   $("settings-form"),
  setActiveProvider: $("set-active-provider"),
  setOpenAIModel: $("set-openai-model"),
  setOpenAIKey:   $("set-openai-key"),
  setOpenAIStatus:$("set-openai-status"),
  setAnthropicModel: $("set-anthropic-model"),
  setAnthropicKey:   $("set-anthropic-key"),
  setAnthropicStatus:$("set-anthropic-status"),
  setGoogleModel: $("set-google-model"),
  setGoogleKey:   $("set-google-key"),
  setGoogleStatus:$("set-google-status"),
  setVaultName:   $("set-vault-name"),
  settingsStatus: $("settings-status"),
  settingsSave:   $("settings-save"),
  importOverlay: $("import-overlay"),
  importClose: $("import-close"),
  importForm:  $("import-form"),
  importSource: $("import-source"),
  importFile:   $("import-file"),
  importProcess:$("import-process"),
  importLimit:  $("import-limit"),
  importSubmit: $("import-submit"),
  importProgress:    $("import-progress"),
  progressBarFill:   $("progress-bar-fill"),
  progressIndex:     $("progress-index"),
  progressTotal:     $("progress-total"),
  progressImported:  $("progress-imported"),
  progressSkipped:   $("progress-skipped"),
  progressFailed:    $("progress-failed"),
  progressCurrent:   $("progress-current"),
  progressError:     $("progress-error"),
};

// ------------ app config (vault name for obsidian:// links) ------------

const appConfig = { vaultName: "", activeProvider: "" };

async function refreshAppConfig() {
  try {
    const cfg = await api("/api/config");
    appConfig.vaultName = cfg.vault_name || "";
    appConfig.activeProvider = cfg.active_provider || "";
  } catch {
    // 401s land here on first load before login — fine, we'll refetch after login
  }
}

function obsidianUrl(path) {
  if (!appConfig.vaultName || !path) return null;
  // Obsidian accepts paths with or without `.md`; strip for cleaner URLs.
  const file = path.replace(/\.md$/i, "");
  return `obsidian://open?vault=${encodeURIComponent(appConfig.vaultName)}&file=${encodeURIComponent(file)}`;
}

/**
 * Build a path link element. If a vault_name is configured, the link opens the
 * note in Obsidian. Otherwise the link copies the path to the clipboard.
 */
function buildPathLink(path, { className = "" } = {}) {
  const a = document.createElement("a");
  if (className) a.className = className;
  a.textContent = path || "";
  const url = obsidianUrl(path);
  if (url) {
    a.href = url;
    a.title = "Open in Obsidian";
    // Don't navigate the PWA away on click — let the obsidian:// scheme handler take over
    a.target = "_blank";
    a.rel = "noopener";
  } else {
    a.href = "#";
    a.title = "Click to copy path";
    a.addEventListener("click", (e) => {
      e.preventDefault();
      copyToClipboard(path || "");
      const prev = a.textContent;
      a.textContent = "copied ✓";
      setTimeout(() => { a.textContent = prev; }, 900);
    });
  }
  return a;
}

// ------------ token storage ------------

const getToken   = () => localStorage.getItem(TOKEN_KEY);
const setToken   = (t) => localStorage.setItem(TOKEN_KEY, t);
const clearToken = () => localStorage.removeItem(TOKEN_KEY);

// ------------ geolocation ------------

// Browser permission state. Once "denied" we stop asking for the rest of the session.
let geoState = "unknown"; // "unknown" | "granted" | "denied" | "unsupported"
let cachedCoords = null;
let cachedCoordsAt = 0;
const GEO_CACHE_MS = 5 * 60 * 1000; // 5 minutes

async function getCoords() {
  if (geoState === "denied" || geoState === "unsupported") return null;
  if (!navigator.geolocation) {
    geoState = "unsupported";
    return null;
  }
  if (cachedCoords && Date.now() - cachedCoordsAt < GEO_CACHE_MS) {
    return cachedCoords;
  }
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        cachedCoords = { lat: pos.coords.latitude, lon: pos.coords.longitude };
        cachedCoordsAt = Date.now();
        geoState = "granted";
        resolve(cachedCoords);
      },
      (err) => {
        if (err && err.code === 1 /* PERMISSION_DENIED */) {
          geoState = "denied";
        }
        // timeouts/position-unavailable: just degrade silently for this send
        resolve(null);
      },
      { timeout: 5000, maximumAge: 10 * 60 * 1000, enableHighAccuracy: false }
    );
  });
}

// ------------ API helpers ------------

async function api(path, { method = "GET", body, auth = true } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth) {
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }
  const res = await fetch(path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  return handleResponse(res);
}

async function apiUpload(path, formData) {
  const headers = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(path, { method: "POST", headers, body: formData });
  return handleResponse(res);
}

async function handleResponse(res) {
  let data = null;
  try { data = await res.json(); } catch { /* no body */ }
  if (!res.ok) {
    const detail = (data && data.detail) || `HTTP ${res.status}`;
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return data;
}

function handleAuthError(err) {
  if (err.status === 401) {
    clearToken();
    setTimeout(initAuth, 600);
    return true;
  }
  return false;
}

// ------------ auth flow ------------

let isSetupMode = false;

async function initAuth() {
  els.app.classList.add("hidden");
  els.messages.innerHTML = "";

  if (getToken()) {
    showApp();
    return;
  }
  try {
    const status = await api("/api/auth/status", { auth: false });
    isSetupMode = !status.has_password;
  } catch {
    isSetupMode = false;
  }
  if (isSetupMode) {
    els.authPrompt.textContent = "First-time setup — choose a password";
    els.authBtn.textContent = "Set password";
  } else {
    els.authPrompt.textContent = "Enter password";
    els.authBtn.textContent = "Continue";
  }
  els.authError.textContent = "";
  els.authScreen.classList.remove("hidden");
  els.authPwd.focus();
}

els.authForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  els.authError.textContent = "";
  els.authBtn.disabled = true;
  const pwd = els.authPwd.value;
  try {
    const endpoint = isSetupMode ? "/api/auth/setup" : "/api/auth/login";
    const { token } = await api(endpoint, { method: "POST", body: { password: pwd }, auth: false });
    setToken(token);
    els.authPwd.value = "";
    showApp();
  } catch (err) {
    els.authError.textContent = err.message;
  } finally {
    els.authBtn.disabled = false;
  }
});

els.logoutBtn.addEventListener("click", () => {
  clearToken();
  initAuth();
});

// ------------ chat UI ------------

function showApp() {
  els.authScreen.classList.add("hidden");
  els.app.classList.remove("hidden");
  els.input.focus();
  if (!els.messages.childElementCount) {
    addBubble("system", "Hi 👋  Type, paste a link, attach an image, or tap the mic to capture. Start a message with ? to ask a question of your notes.");
  }
  // Vault name is needed to build obsidian:// links
  refreshAppConfig();
}

function addBubble(kind, text, opts = {}) {
  const div = document.createElement("div");
  div.className = `bubble ${kind}`;
  if (opts.pending) div.classList.add("pending");
  div.textContent = text;
  els.messages.appendChild(div);
  scrollToBottom();
  return div;
}

function addImageBubble(objectUrl) {
  const div = document.createElement("div");
  div.className = "bubble me image-bubble";
  const img = document.createElement("img");
  img.src = objectUrl;
  img.alt = "Captured image";
  div.appendChild(img);
  els.messages.appendChild(div);
  scrollToBottom();
  return div;
}

function addLinkBubble(url) {
  const div = document.createElement("div");
  div.className = "bubble me link-bubble";
  let host = url;
  try { host = new URL(url).hostname; } catch {}
  const hostEl = document.createElement("div");
  hostEl.className = "link-host";
  hostEl.textContent = `🔗 ${host}`;
  const urlEl = document.createElement("div");
  urlEl.textContent = url;
  div.appendChild(hostEl);
  div.appendChild(urlEl);
  els.messages.appendChild(div);
  scrollToBottom();
  return div;
}

function addCaptureResult(result) {
  const div = document.createElement("div");
  div.className = "bubble system";

  if (result.title && result.page_title) {
    // Link capture: show page title prominently
    const t = document.createElement("div");
    t.className = "title";
    t.textContent = result.page_title;
    div.appendChild(t);
  }

  const summary = document.createElement("div");
  summary.className = "summary";
  summary.textContent = result.summary || result.title || "Saved.";
  div.appendChild(summary);

  if (result.tags && result.tags.length) {
    const tags = document.createElement("div");
    tags.className = "tags";
    for (const t of result.tags) {
      const span = document.createElement("span");
      span.className = "tag";
      span.textContent = `#${t}`;
      tags.appendChild(span);
    }
    div.appendChild(tags);
  }

  const meta = document.createElement("span");
  meta.className = "meta";
  meta.appendChild(document.createTextNode("Filed to "));
  meta.appendChild(buildPathLink(result.filed_to, { className: "filed" }));
  div.appendChild(meta);

  els.messages.appendChild(div);
  scrollToBottom();
}

function scrollToBottom() {
  els.messages.scrollTop = els.messages.scrollHeight;
}

// auto-grow textarea
function autoGrow() {
  els.input.style.height = "auto";
  els.input.style.height = Math.min(els.input.scrollHeight, 160) + "px";
}
els.input.addEventListener("input", autoGrow);

// Enter sends, Shift+Enter inserts newline
els.input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

els.sendBtn.addEventListener("click", sendMessage);

// ------------ send (text or link, auto-detected) ------------

function isJustUrl(text) {
  if (!text) return false;
  if (/\s/.test(text)) return false;          // any whitespace → treat as text
  if (!/^https?:\/\//i.test(text)) return false;
  try {
    const u = new URL(text);
    return u.protocol === "http:" || u.protocol === "https:";
  } catch {
    return false;
  }
}

async function sendMessage() {
  const text = els.input.value.trim();
  if (!text) return;
  els.input.value = "";
  autoGrow();

  if (text.startsWith("?")) {
    const question = text.slice(1).trim();
    if (question) await askQuestion(question);
    return;
  }
  if (isJustUrl(text)) {
    await captureLink(text);
  } else {
    await captureText(text);
  }
}

async function askQuestion(question) {
  addBubble("me", `? ${question}`);
  const pending = addBubble("system", "Thinking…", { pending: true });
  try {
    const result = await api("/api/ask", { method: "POST", body: { question } });
    pending.remove();
    addAnswerBubble(result);
  } catch (err) {
    pending.remove();
    if (handleAuthError(err)) {
      addBubble("error", "Session expired — please log in again.");
    } else {
      addBubble("error", `Couldn't answer: ${err.message}`);
    }
  }
}

function addAnswerBubble(result) {
  const div = document.createElement("div");
  div.className = "bubble system answer-bubble";

  const answer = document.createElement("div");
  answer.className = "answer";
  answer.textContent = result.answer || "(no answer)";
  div.appendChild(answer);

  if (result.sources && result.sources.length) {
    const srcWrap = document.createElement("div");
    srcWrap.className = "sources";
    const heading = document.createElement("div");
    heading.className = "sources-heading";
    heading.textContent = `Sources (${result.sources.length})`;
    srcWrap.appendChild(heading);
    for (const s of result.sources) {
      const row = document.createElement("div");
      row.className = "source-row";
      const title = document.createElement("span");
      title.className = "source-title";
      title.textContent = s.title || "(untitled)";
      row.appendChild(title);
      row.appendChild(document.createTextNode(" · "));
      row.appendChild(buildPathLink(s.path, { className: "source-path filed" }));
      const score = document.createElement("span");
      score.className = "source-score";
      score.textContent = ` · ${(s.score * 100).toFixed(0)}%`;
      row.appendChild(score);
      srcWrap.appendChild(row);
    }
    div.appendChild(srcWrap);
  }

  els.messages.appendChild(div);
  scrollToBottom();
}

async function captureText(text) {
  addBubble("me", text);
  const pending = addBubble("system", "Filing…", { pending: true });
  const coords = await getCoords();
  const body = { content: text };
  if (coords) body.context = coords;
  try {
    const result = await api("/api/capture/text", { method: "POST", body });
    pending.remove();
    addCaptureResult(result);
  } catch (err) {
    pending.remove();
    if (handleAuthError(err)) {
      addBubble("error", "Session expired — please log in again.");
    } else if (isOfflineError(err)) {
      try {
        await enqueueCapture({ kind: "text", payload: body });
        addBubble("system", "📵 Offline — queued. Will sync when connected.", { pending: true });
        updateOfflineBadge();
      } catch (qerr) {
        addBubble("error", `Couldn't queue offline: ${qerr.message}`);
      }
    } else {
      addBubble("error", `Couldn't file that: ${err.message}`);
    }
  }
}

async function captureLink(url) {
  addLinkBubble(url);
  const pending = addBubble("system", "Fetching link…", { pending: true });
  const coords = await getCoords();
  const body = { url };
  if (coords) body.context = coords;
  try {
    const result = await api("/api/capture/link", { method: "POST", body });
    pending.remove();
    addCaptureResult(result);
  } catch (err) {
    pending.remove();
    if (handleAuthError(err)) {
      addBubble("error", "Session expired — please log in again.");
    } else if (isOfflineError(err)) {
      try {
        await enqueueCapture({ kind: "link", payload: body });
        addBubble("system", "📵 Offline — link queued. Will sync when connected.", { pending: true });
        updateOfflineBadge();
      } catch (qerr) {
        addBubble("error", `Couldn't queue offline: ${qerr.message}`);
      }
    } else {
      addBubble("error", `Couldn't fetch link: ${err.message}`);
    }
  }
}

// ------------ image capture ------------

els.attachBtn.addEventListener("click", () => {
  els.imageInput.click();
});

els.imageInput.addEventListener("change", async (e) => {
  const file = e.target.files && e.target.files[0];
  e.target.value = ""; // allow re-selecting the same file
  if (!file) return;
  await captureImage(file);
});

async function captureImage(file) {
  const objectUrl = URL.createObjectURL(file);
  addImageBubble(objectUrl);
  const pending = addBubble("system", "Analyzing image…", { pending: true });

  const formData = new FormData();
  formData.append("file", file, file.name || "image");
  const coords = await getCoords();
  if (coords) {
    formData.append("lat", String(coords.lat));
    formData.append("lon", String(coords.lon));
  }

  try {
    const result = await apiUpload("/api/capture/image", formData);
    pending.remove();
    addCaptureResult(result);
  } catch (err) {
    pending.remove();
    if (handleAuthError(err)) {
      addBubble("error", "Session expired — please log in again.");
    } else {
      addBubble("error", `Couldn't process image: ${err.message}`);
    }
  }
}

// ------------ voice capture ------------

let recorder = null;
let recordingChunks = [];
let recordingStream = null;
let recordingStartTime = 0;
let recordingTimer = null;
const previousPlaceholder = "Capture a thought…";

els.micBtn.addEventListener("click", async () => {
  if (recorder && recorder.state === "recording") {
    recorder.stop();
    return;
  }
  await startRecording();
});

async function startRecording() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    addBubble("error", "This browser doesn't support audio recording.");
    return;
  }

  try {
    recordingStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    addBubble("error", `Microphone access denied: ${err.message}`);
    return;
  }

  // Pick a mime type the browser actually supports
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/mp4",
    "audio/ogg;codecs=opus",
    "",
  ];
  let chosenMime = "";
  for (const c of candidates) {
    if (c === "" || (window.MediaRecorder && MediaRecorder.isTypeSupported(c))) {
      chosenMime = c;
      break;
    }
  }

  try {
    recorder = chosenMime
      ? new MediaRecorder(recordingStream, { mimeType: chosenMime })
      : new MediaRecorder(recordingStream);
  } catch (err) {
    stopStream();
    addBubble("error", `Couldn't start recorder: ${err.message}`);
    return;
  }

  recordingChunks = [];
  recorder.ondataavailable = (e) => {
    if (e.data && e.data.size > 0) recordingChunks.push(e.data);
  };
  recorder.onstop = handleRecordingStop;

  recorder.start();
  startRecordingUI();
}

async function handleRecordingStop() {
  stopStream();
  stopRecordingUI();

  const mime = recorder.mimeType || "audio/webm";
  const blob = new Blob(recordingChunks, { type: mime });

  const ext =
    mime.includes("webm") ? "webm" :
    mime.includes("mp4")  ? "m4a"  :
    mime.includes("ogg")  ? "ogg"  :
    "webm";
  const filename = `voice-${Date.now()}.${ext}`;

  if (blob.size < 200) {
    addBubble("error", "Recording was too short — try again.");
    return;
  }

  const pending = addBubble("system", "Transcribing…", { pending: true });

  const formData = new FormData();
  formData.append("file", blob, filename);
  const coords = await getCoords();
  if (coords) {
    formData.append("lat", String(coords.lat));
    formData.append("lon", String(coords.lon));
  }

  try {
    const result = await apiUpload("/api/capture/voice", formData);
    pending.remove();
    addBubble("me", `🎙️ ${result.transcript}`);
    addCaptureResult(result);
  } catch (err) {
    pending.remove();
    if (handleAuthError(err)) {
      addBubble("error", "Session expired — please log in again.");
    } else {
      addBubble("error", `Couldn't transcribe: ${err.message}`);
    }
  }
}

function stopStream() {
  if (recordingStream) {
    recordingStream.getTracks().forEach((t) => t.stop());
    recordingStream = null;
  }
}

function startRecordingUI() {
  els.micBtn.classList.add("recording");
  els.micBtn.setAttribute("aria-label", "Stop recording");
  els.input.disabled = true;
  els.sendBtn.disabled = true;
  els.attachBtn.disabled = true;
  recordingStartTime = Date.now();
  updateRecordingDuration();
  recordingTimer = setInterval(updateRecordingDuration, 250);
}

function stopRecordingUI() {
  els.micBtn.classList.remove("recording");
  els.micBtn.setAttribute("aria-label", "Record voice");
  clearInterval(recordingTimer);
  recordingTimer = null;
  els.input.placeholder = previousPlaceholder;
  els.input.disabled = false;
  els.sendBtn.disabled = false;
  els.attachBtn.disabled = false;
}

function updateRecordingDuration() {
  const elapsed = Math.floor((Date.now() - recordingStartTime) / 1000);
  const mm = String(Math.floor(elapsed / 60)).padStart(2, "0");
  const ss = String(elapsed % 60).padStart(2, "0");
  els.input.placeholder = `🔴 Recording…  ${mm}:${ss}  (tap mic to stop)`;
}

// ------------ search ------------

els.searchBtn.addEventListener("click", openSearch);
els.searchClose.addEventListener("click", closeSearch);
els.searchOverlay.addEventListener("click", (e) => {
  if (e.target === els.searchOverlay) closeSearch();
});

let searchDebounce = null;
let searchSeq = 0;

function openSearch() {
  if (!getToken()) return;
  els.searchOverlay.classList.remove("hidden");
  els.searchInput.focus();
  els.searchInput.select();
}

function closeSearch() {
  els.searchOverlay.classList.add("hidden");
}

els.searchInput.addEventListener("input", () => scheduleSearch(280));
els.searchInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    runSearch();
  } else if (e.key === "Escape") {
    closeSearch();
  }
});
els.searchType.addEventListener("change", () => scheduleSearch(0));
els.searchSource.addEventListener("change", () => scheduleSearch(0));

function scheduleSearch(delay) {
  clearTimeout(searchDebounce);
  searchDebounce = setTimeout(runSearch, delay);
}

async function runSearch() {
  const query = els.searchInput.value.trim();
  if (!query) {
    els.searchResults.innerHTML = "";
    els.searchStatus.classList.remove("error");
    els.searchStatus.textContent = "";
    return;
  }

  const mySeq = ++searchSeq;
  els.searchStatus.classList.remove("error");
  els.searchStatus.textContent = "Searching…";

  const body = { query, limit: 20 };
  if (els.searchType.value)   body.type = els.searchType.value;
  if (els.searchSource.value) body.source = els.searchSource.value;

  try {
    const res = await api("/api/search", { method: "POST", body });
    if (mySeq !== searchSeq) return; // a newer query already started
    renderSearchResults(res.results || []);
  } catch (err) {
    if (mySeq !== searchSeq) return;
    if (handleAuthError(err)) {
      els.searchStatus.textContent = "Session expired — please log in again.";
    } else {
      els.searchStatus.textContent = err.message;
    }
    els.searchStatus.classList.add("error");
    els.searchResults.innerHTML = "";
  }
}

function renderSearchResults(results) {
  els.searchResults.innerHTML = "";
  if (!results.length) {
    els.searchStatus.textContent = "No matches.";
    return;
  }
  els.searchStatus.textContent = `${results.length} result${results.length === 1 ? "" : "s"}`;

  for (const r of results) {
    els.searchResults.appendChild(buildResultCard(r));
  }
}

function buildResultCard(r) {
  const li = document.createElement("li");
  li.className = "result-card";

  const head = document.createElement("div");
  head.className = "result-head";
  const title = document.createElement("div");
  title.className = "result-title";
  title.textContent = r.title || "(untitled)";
  head.appendChild(title);
  if (typeof r.score === "number") {
    const score = document.createElement("span");
    score.className = "result-score";
    score.textContent = `${Math.round(r.score * 100)}%`;
    head.appendChild(score);
  }
  li.appendChild(head);

  const meta = document.createElement("div");
  meta.className = "result-meta";
  meta.appendChild(buildPathLink(r.path, { className: "result-path" }));
  if (r.type)   { addDot(meta); meta.appendChild(textSpan(r.type)); }
  if (r.source) { addDot(meta); meta.appendChild(textSpan(r.source)); }
  if (r.date)   { addDot(meta); meta.appendChild(textSpan(r.date.slice(0, 16).replace("T", " "))); }
  li.appendChild(meta);

  if (r.snippet) {
    const snippet = document.createElement("div");
    snippet.className = "result-snippet";
    snippet.textContent = r.snippet;
    li.appendChild(snippet);
  }

  if (r.tags && r.tags.length) {
    const tags = document.createElement("div");
    tags.className = "result-tags";
    for (const t of r.tags) {
      const span = document.createElement("span");
      span.className = "tag";
      span.textContent = `#${t}`;
      tags.appendChild(span);
    }
    li.appendChild(tags);
  }

  return li;
}

function addDot(parent) {
  const dot = document.createElement("span");
  dot.className = "dot";
  dot.textContent = "·";
  parent.appendChild(dot);
}

function textSpan(text) {
  const s = document.createElement("span");
  s.textContent = text;
  return s;
}

function copyToClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).catch(() => fallbackCopy(text));
  } else {
    fallbackCopy(text);
  }
}

function fallbackCopy(text) {
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.left = "-9999px";
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand("copy"); } catch {}
  document.body.removeChild(ta);
}

// ------------ settings ------------

els.settingsBtn.addEventListener("click", openSettings);
els.settingsClose.addEventListener("click", closeSettings);
els.settingsOverlay.addEventListener("click", (e) => {
  if (e.target === els.settingsOverlay) closeSettings();
});

async function openSettings() {
  if (!getToken()) return;
  els.settingsOverlay.classList.remove("hidden");
  els.settingsStatus.textContent = "";
  els.settingsStatus.classList.remove("error");
  await loadSettings();
}

function closeSettings() {
  els.settingsOverlay.classList.add("hidden");
}

function setStatusBadge(el, configured) {
  el.textContent = configured ? "configured" : "not configured";
  el.classList.toggle("configured", !!configured);
}

async function loadSettings() {
  try {
    const s = await api("/api/settings");
    els.setActiveProvider.value = s.active_provider || "openai";
    els.setOpenAIModel.value    = s.openai_model || "";
    els.setAnthropicModel.value = s.anthropic_model || "";
    els.setGoogleModel.value    = s.google_model || "";
    els.setVaultName.value      = s.vault_name || "";
    setStatusBadge(els.setOpenAIStatus,    s.openai_configured);
    setStatusBadge(els.setAnthropicStatus, s.anthropic_configured);
    setStatusBadge(els.setGoogleStatus,    s.google_configured);
    // Always start key inputs blank — they're write-only
    els.setOpenAIKey.value = "";
    els.setAnthropicKey.value = "";
    els.setGoogleKey.value = "";
  } catch (err) {
    if (handleAuthError(err)) {
      els.settingsStatus.textContent = "Session expired — please log in again.";
    } else {
      els.settingsStatus.textContent = err.message;
    }
    els.settingsStatus.classList.add("error");
  }
}

els.settingsForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  els.settingsSave.disabled = true;
  els.settingsStatus.classList.remove("error");
  els.settingsStatus.textContent = "Saving…";

  const body = {
    active_provider: els.setActiveProvider.value,
    openai_model:    els.setOpenAIModel.value.trim(),
    anthropic_model: els.setAnthropicModel.value.trim(),
    google_model:    els.setGoogleModel.value.trim(),
    vault_name:      els.setVaultName.value.trim(),
  };
  // Only include key fields if user actually typed something — empty means "no change".
  if (els.setOpenAIKey.value)    body.openai_api_key    = els.setOpenAIKey.value;
  if (els.setAnthropicKey.value) body.anthropic_api_key = els.setAnthropicKey.value;
  if (els.setGoogleKey.value)    body.google_api_key    = els.setGoogleKey.value;

  try {
    const updated = await api("/api/settings", { method: "PUT", body });
    els.settingsStatus.textContent = "Saved.";
    setStatusBadge(els.setOpenAIStatus,    updated.openai_configured);
    setStatusBadge(els.setAnthropicStatus, updated.anthropic_configured);
    setStatusBadge(els.setGoogleStatus,    updated.google_configured);
    els.setOpenAIKey.value = "";
    els.setAnthropicKey.value = "";
    els.setGoogleKey.value = "";
    // Pull fresh app config in case vault_name changed (drives obsidian:// URLs)
    refreshAppConfig();
  } catch (err) {
    if (handleAuthError(err)) {
      els.settingsStatus.textContent = "Session expired — please log in again.";
    } else {
      els.settingsStatus.textContent = err.message;
    }
    els.settingsStatus.classList.add("error");
  } finally {
    els.settingsSave.disabled = false;
  }
});

// ------------ browse ------------

const BROWSE_PAGE_SIZE = 30;
let browseOffset = 0;
let browseLoading = false;

els.browseBtn.addEventListener("click", openBrowse);
els.browseClose.addEventListener("click", closeBrowse);
els.browseOverlay.addEventListener("click", (e) => {
  if (e.target === els.browseOverlay) closeBrowse();
});

els.browseType.addEventListener("change", () => resetBrowse());
els.browseSource.addEventListener("change", () => resetBrowse());
els.browseTag.addEventListener("change", () => resetBrowse());
els.browseReset.addEventListener("click", () => {
  els.browseType.value = "";
  els.browseSource.value = "";
  els.browseTag.value = "";
  resetBrowse();
});
els.browseMore.addEventListener("click", loadBrowse);

async function openBrowse() {
  if (!getToken()) return;
  els.browseOverlay.classList.remove("hidden");
  await Promise.all([loadTagOptions(), resetBrowse()]);
}

function closeBrowse() {
  els.browseOverlay.classList.add("hidden");
}

async function loadTagOptions() {
  try {
    const res = await api("/api/tags?limit=200");
    const sel = els.browseTag;
    const current = sel.value;
    // Wipe everything except the placeholder
    while (sel.options.length > 1) sel.remove(1);
    for (const t of res.tags || []) {
      const opt = document.createElement("option");
      opt.value = t.tag;
      opt.textContent = `#${t.tag} (${t.count})`;
      sel.appendChild(opt);
    }
    if (current && Array.from(sel.options).some(o => o.value === current)) {
      sel.value = current;
    }
  } catch (err) {
    if (handleAuthError(err)) return;
    // tag list is non-critical
  }
}

async function resetBrowse() {
  browseOffset = 0;
  els.browseResults.innerHTML = "";
  els.browseStatus.classList.remove("error");
  els.browseStatus.textContent = "Loading…";
  els.browseMore.classList.add("hidden");
  await loadBrowse();
}

async function loadBrowse() {
  if (browseLoading) return;
  browseLoading = true;
  els.browseMore.disabled = true;

  const params = new URLSearchParams({
    limit: String(BROWSE_PAGE_SIZE),
    offset: String(browseOffset),
  });
  if (els.browseType.value)   params.set("type", els.browseType.value);
  if (els.browseSource.value) params.set("source", els.browseSource.value);
  if (els.browseTag.value)    params.set("tag", els.browseTag.value);

  try {
    const res = await api(`/api/notes/recent?${params}`);
    appendBrowseResults(res.notes || []);
    const shown = browseOffset + (res.notes || []).length;
    els.browseStatus.textContent =
      `${res.total} note${res.total === 1 ? "" : "s"} total · showing ${shown}`;
    if (shown < res.total) {
      els.browseOffset = shown;
      browseOffset = shown;
      els.browseMore.classList.remove("hidden");
    } else {
      els.browseMore.classList.add("hidden");
    }
  } catch (err) {
    if (handleAuthError(err)) {
      els.browseStatus.textContent = "Session expired — please log in again.";
    } else {
      els.browseStatus.textContent = err.message;
    }
    els.browseStatus.classList.add("error");
  } finally {
    browseLoading = false;
    els.browseMore.disabled = false;
  }
}

function appendBrowseResults(notes) {
  for (const n of notes) {
    els.browseResults.appendChild(buildBrowseCard(n));
  }
}

function buildBrowseCard(n) {
  const li = document.createElement("li");
  li.className = "result-card";

  const head = document.createElement("div");
  head.className = "result-head";
  const title = document.createElement("div");
  title.className = "result-title";
  title.textContent = n.title || "(untitled)";
  head.appendChild(title);
  li.appendChild(head);

  const meta = document.createElement("div");
  meta.className = "result-meta";
  meta.appendChild(buildPathLink(n.path, { className: "result-path" }));
  if (n.type)     { addDot(meta); meta.appendChild(textSpan(n.type)); }
  if (n.source)   { addDot(meta); meta.appendChild(textSpan(n.source)); }
  if (n.category) { addDot(meta); meta.appendChild(textSpan(n.category)); }
  if (n.date)     { addDot(meta); meta.appendChild(textSpan(n.date.slice(0, 16).replace("T", " "))); }
  li.appendChild(meta);

  if (n.summary) {
    const summary = document.createElement("div");
    summary.className = "result-snippet";
    summary.textContent = n.summary;
    li.appendChild(summary);
  }

  if (n.tags && n.tags.length) {
    const tags = document.createElement("div");
    tags.className = "result-tags";
    for (const t of n.tags) {
      const span = document.createElement("span");
      span.className = "tag";
      span.textContent = `#${t}`;
      tags.appendChild(span);
    }
    li.appendChild(tags);
  }

  return li;
}

// ------------ import (chat history) ------------

els.importBtn.addEventListener("click", openImport);
els.importClose.addEventListener("click", closeImport);
els.importOverlay.addEventListener("click", (e) => {
  if (e.target === els.importOverlay) closeImport();
});

function openImport() {
  if (!getToken()) return;
  resetImportForm();
  els.importOverlay.classList.remove("hidden");
}

function closeImport() {
  if (importInFlight) return; // don't allow closing mid-import
  els.importOverlay.classList.add("hidden");
}

function resetImportForm() {
  els.importFile.value = "";
  els.importLimit.value = "";
  els.importProcess.checked = true;
  els.importSubmit.disabled = false;
  els.importSubmit.textContent = "Start import";
  els.importProgress.classList.add("hidden");
  els.importProgress.classList.remove("done");
  els.progressBarFill.style.width = "0%";
  els.progressIndex.textContent = "0";
  els.progressTotal.textContent = "0";
  els.progressImported.textContent = "0";
  els.progressSkipped.textContent = "0";
  els.progressFailed.textContent = "0";
  els.progressCurrent.textContent = "";
  els.progressError.textContent = "";
}

let importInFlight = false;

els.importForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (importInFlight) return;

  const file = els.importFile.files && els.importFile.files[0];
  if (!file) return;

  const source = els.importSource.value;
  const process = els.importProcess.checked;
  const limitRaw = els.importLimit.value.trim();
  const limit = limitRaw ? Math.max(1, parseInt(limitRaw, 10) || 0) : null;

  importInFlight = true;
  els.importSubmit.disabled = true;
  els.importSubmit.textContent = "Importing…";
  els.importProgress.classList.remove("hidden");
  els.importProgress.classList.remove("done");
  els.progressError.textContent = "";

  const fd = new FormData();
  fd.append("file", file);
  fd.append("process", process ? "true" : "false");
  if (limit) fd.append("limit", String(limit));

  try {
    await streamImport(source, fd);
  } catch (err) {
    if (handleAuthError(err)) {
      els.progressError.textContent = "Session expired — please log in again.";
    } else {
      els.progressError.textContent = err.message;
    }
  } finally {
    importInFlight = false;
    els.importSubmit.disabled = false;
    els.importSubmit.textContent = "Start import";
  }
});

async function streamImport(source, formData) {
  const token = getToken();
  const headers = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`/api/import/${source}/stream`, {
    method: "POST",
    headers,
    body: formData,
  });

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try { const data = await res.json(); detail = (data && data.detail) || detail; } catch {}
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }

  if (!res.body) {
    throw new Error("Streaming not supported by this browser");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE events are separated by blank lines
    let sepIdx;
    while ((sepIdx = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, sepIdx);
      buffer = buffer.slice(sepIdx + 2);
      handleSseBlock(block);
    }
  }
  // Flush trailing
  if (buffer.trim()) handleSseBlock(buffer);
}

function handleSseBlock(block) {
  // Each block can have multiple data: lines; join them.
  const dataLines = block.split("\n").filter(l => l.startsWith("data: ")).map(l => l.slice(6));
  if (!dataLines.length) return;
  const payload = dataLines.join("\n");
  let event;
  try { event = JSON.parse(payload); } catch { return; }
  applyProgressEvent(event);
}

function applyProgressEvent(ev) {
  if (ev.phase === "started") {
    els.progressTotal.textContent = String(ev.total || 0);
    els.progressIndex.textContent = "0";
    els.progressBarFill.style.width = ev.total ? "1%" : "0%";
    return;
  }
  if (ev.phase === "progress") {
    els.progressTotal.textContent = String(ev.total || 0);
    els.progressIndex.textContent = String(ev.index || 0);
    els.progressImported.textContent = String(ev.imported || 0);
    els.progressSkipped.textContent = String(ev.skipped || 0);
    els.progressFailed.textContent = String(ev.failed || 0);
    els.progressCurrent.textContent = ev.title ? `current: ${ev.title}` : "";
    const pct = ev.total ? Math.max(1, Math.min(100, Math.round((ev.index / ev.total) * 100))) : 0;
    els.progressBarFill.style.width = pct + "%";
    return;
  }
  if (ev.phase === "done") {
    els.progressTotal.textContent = String(ev.total || 0);
    els.progressIndex.textContent = String(ev.total || 0);
    els.progressImported.textContent = String(ev.imported || 0);
    els.progressSkipped.textContent = String(ev.skipped || 0);
    els.progressFailed.textContent = String(ev.failed || 0);
    els.progressBarFill.style.width = "100%";
    els.progressCurrent.textContent =
      `Done — ${ev.imported} imported, ${ev.skipped} skipped, ${ev.failed} failed.`;
    els.importProgress.classList.add("done");
    return;
  }
  if (ev.phase === "error") {
    els.progressError.textContent = ev.detail || "Import failed.";
    return;
  }
}

// ------------ offline queue (IndexedDB) ------------

const QUEUE_DB_NAME = "second_brain";
const QUEUE_DB_VERSION = 1;
const QUEUE_STORE = "capture_queue";
const offlineBadge = document.getElementById("offline-badge");

function updateOfflineBadge() {
  if (!offlineBadge) return;
  if (navigator.onLine) offlineBadge.classList.add("hidden");
  else offlineBadge.classList.remove("hidden");
}
window.addEventListener("online",  () => { updateOfflineBadge(); drainQueue(); });
window.addEventListener("offline", updateOfflineBadge);
updateOfflineBadge();

function isOfflineError(err) {
  if (!navigator.onLine) return true;
  // fetch() against an unreachable server throws TypeError("Failed to fetch")
  if (err && err.name === "TypeError") return true;
  if (err && /failed to fetch|networkerror|load failed/i.test(err.message || "")) return true;
  return false;
}

function openQueueDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(QUEUE_DB_NAME, QUEUE_DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(QUEUE_STORE)) {
        db.createObjectStore(QUEUE_STORE, { keyPath: "id", autoIncrement: true });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror   = () => reject(req.error);
  });
}

async function enqueueCapture(item) {
  const db = await openQueueDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(QUEUE_STORE, "readwrite");
    tx.objectStore(QUEUE_STORE).add({ ...item, queuedAt: Date.now() });
    tx.oncomplete = () => resolve();
    tx.onerror    = () => reject(tx.error);
  });
}

async function listQueue() {
  const db = await openQueueDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(QUEUE_STORE, "readonly");
    const req = tx.objectStore(QUEUE_STORE).getAll();
    req.onsuccess = () => resolve(req.result || []);
    req.onerror   = () => reject(req.error);
  });
}

async function removeQueueItem(id) {
  const db = await openQueueDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(QUEUE_STORE, "readwrite");
    tx.objectStore(QUEUE_STORE).delete(id);
    tx.oncomplete = () => resolve();
    tx.onerror    = () => reject(tx.error);
  });
}

let draining = false;

async function drainQueue() {
  if (draining || !getToken()) return;
  let items;
  try { items = await listQueue(); } catch { return; }
  if (!items.length) return;

  draining = true;
  addBubble("system", `🔄 Syncing ${items.length} queued message${items.length === 1 ? "" : "s"}…`);

  for (const item of items) {
    try {
      let result;
      if (item.kind === "text") {
        result = await api("/api/capture/text", { method: "POST", body: item.payload });
      } else if (item.kind === "link") {
        result = await api("/api/capture/link", { method: "POST", body: item.payload });
      }
      await removeQueueItem(item.id);
      if (result) addCaptureResult(result);
    } catch (err) {
      // Stop on first failure — wait for next online event
      break;
    }
  }
  draining = false;
}

// ------------ kickoff ------------

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}

initAuth();
// In case there's a queue from a previous session, try a drain shortly after init.
setTimeout(() => { if (getToken()) drainQueue(); }, 1500);
