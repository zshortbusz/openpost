/* OpenPost Frontend State & API Controller */

const state = {
  collections: [],
  environments: [],
  activeCollectionId: null,
  activeRequestId: null,
};

const API_BASE =
  window.location.protocol.startsWith("http") &&
  (window.location.port === "8000" ||
    window.location.hostname === "127.0.0.1" ||
    window.location.hostname === "localhost")
    ? ""
    : "http://127.0.0.1:8000";

async function api(path, options = {}) {
  const fullPath = path.startsWith("http") ? path : `${API_BASE}${path}`;
  const res = await fetch(fullPath, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "API Error");
  }
  return res.json();
}

function parseJsonSafe(text, fallback) {
  if (!text || !text.trim()) return fallback;
  try {
    return JSON.parse(text);
  } catch {
    return fallback;
  }
}

function buildCurrentAuth() {
  const type = document.getElementById("authTypeSelect").value;
  const val = document.getElementById("authTokenInput").value.trim();
  if (type === "noauth" || !val) return null;
  if (type === "bearer") return { type: "bearer", params: { token: val } };
  if (type === "apikey") return { type: "apikey", params: { key: "X-API-Key", value: val, in: "header" } };
  if (type === "basic") {
    const colonIdx = val.indexOf(":");
    const username = colonIdx >= 0 ? val.slice(0, colonIdx) : val;
    const password = colonIdx >= 0 ? val.slice(colonIdx + 1) : "";
    return { type: "basic", params: { username, password } };
  }
  return null;
}

function populateAuthFields(auth) {
  const typeSelect = document.getElementById("authTypeSelect");
  const tokenInput = document.getElementById("authTokenInput");
  if (!auth || !auth.type || auth.type === "noauth") {
    typeSelect.value = "noauth";
    tokenInput.value = "";
    return;
  }
  const type = auth.type.toLowerCase();
  const params = auth.params || {};
  if (type === "bearer") {
    typeSelect.value = "bearer";
    tokenInput.value = params.token || "";
  } else if (type === "apikey") {
    typeSelect.value = "apikey";
    tokenInput.value = params.value || "";
  } else if (type === "basic") {
    typeSelect.value = "basic";
    const u = params.username || "";
    const p = params.password || "";
    tokenInput.value = u || p ? `${u}:${p}` : "";
  } else {
    typeSelect.value = "noauth";
    tokenInput.value = "";
  }
}

function buildCurrentBody() {
  const rawBody = document.getElementById("bodyInput").value;
  if (!rawBody.trim()) return null;
  const parsed = parseJsonSafe(rawBody, null);
  if (
    parsed &&
    typeof parsed === "object" &&
    !Array.isArray(parsed) &&
    typeof parsed.mode === "string" &&
    ["raw", "urlencoded", "formdata", "graphql", "file"].includes(parsed.mode)
  ) {
    return parsed;
  }
  return { mode: "raw", raw: rawBody, language: "json" };
}

async function refreshSandboxStatus() {
  const badge = document.getElementById("sandboxBadge");
  if (!badge) return;
  try {
    await api("/api/health");
    badge.textContent = "Clean-Room: 100% Local";
    badge.style.borderColor = "#10b981";
    badge.style.color = "#10b981";
  } catch {
    badge.textContent = "Backend Offline";
    badge.style.borderColor = "#ef4444";
    badge.style.color = "#ef4444";
  }
}

async function loadEnvironments() {
  state.environments = await api("/api/environments");
  const select = document.getElementById("envSelect");
  const current = select.value;
  select.innerHTML = '<option value="">No Environment</option>';
  for (const env of state.environments) {
    const opt = document.createElement("option");
    opt.value = env.id;
    opt.textContent = `${env.name} (${env.variables.length} vars)`;
    select.appendChild(opt);
  }
  select.value = current;
}

async function loadCollections() {
  state.collections = await api("/api/collections");
  const container = document.getElementById("collectionsList");
  container.innerHTML = "";

  if (state.collections.length === 0) {
    container.innerHTML = '<div style="color:#8b95a7;font-size:12px;padding:8px;">No collections yet. Click "Import v2.1.0 JSON" or "+ Collection".</div>';
    return;
  }

  for (const colSummary of state.collections) {
    const colDetail = await api(`/api/collections/${colSummary.id}`);
    const header = document.createElement("div");
    header.className = "tree-item";
    header.style.fontWeight = "600";
    const titleSpan = document.createElement("span");
    titleSpan.textContent = `📁 ${colDetail.name}`;
    const countSpan = document.createElement("span");
    countSpan.style.color = "#8b95a7";
    countSpan.textContent = String(colDetail.requests.length);
    header.append(titleSpan, countSpan);
    header.onclick = () => {
      state.activeCollectionId = colDetail.id;
      state.activeRequestId = null;
      document.getElementById("activeReqLabel").textContent = `Collection: ${colDetail.name}`;
    };
    container.appendChild(header);

    for (const req of colDetail.requests) {
      const item = document.createElement("div");
      item.className = "tree-item";
      item.style.paddingLeft = "22px";
      const folderPrefix = req.folder_path && req.folder_path.length ? `${req.folder_path.join("/")}/ ` : "";
      const wrapSpan = document.createElement("span");
      const methodTag = document.createElement("span");
      methodTag.className = `method-tag method-${req.method}`;
      methodTag.textContent = req.method;
      wrapSpan.appendChild(methodTag);
      wrapSpan.appendChild(document.createTextNode(`${folderPrefix}${req.name}`));
      item.appendChild(wrapSpan);
      item.onclick = () => selectSavedRequest(colDetail.id, req);
      container.appendChild(item);
    }
  }
}

function selectSavedRequest(collectionId, req) {
  state.activeCollectionId = collectionId;
  state.activeRequestId = req.id;
  document.getElementById("methodSelect").value = req.method || "GET";
  document.getElementById("urlInput").value = req.raw_url || "";
  document.getElementById("paramsInput").value = JSON.stringify(req.query_params || [], null, 2);
  document.getElementById("headersInput").value = JSON.stringify(req.headers || [], null, 2);
  if (!req.body) {
    document.getElementById("bodyInput").value = "";
  } else if (req.body.mode === "raw" || req.body.raw !== undefined) {
    document.getElementById("bodyInput").value = req.body.raw || "";
  } else {
    document.getElementById("bodyInput").value = JSON.stringify(req.body, null, 2);
  }
  populateAuthFields(req.auth);
  document.getElementById("activeReqLabel").textContent = `${req.name} (${req.id.slice(0, 8)})`;
}

async function loadHistory() {
  const history = await api("/api/history?limit=40");
  const container = document.getElementById("historyList");
  container.innerHTML = "";
  for (const h of history) {
    const item = document.createElement("div");
    item.className = "tree-item";
    const leftSpan = document.createElement("span");
    const methodTag = document.createElement("span");
    methodTag.className = `method-tag method-${h.method}`;
    methodTag.textContent = h.method;
    leftSpan.appendChild(methodTag);
    leftSpan.appendChild(document.createTextNode(h.url.slice(0, 28)));
    const statusSpan = document.createElement("span");
    statusSpan.style.color = "#8b95a7";
    statusSpan.textContent = String(h.status_code);
    item.append(leftSpan, statusSpan);
    item.onclick = async () => {
      const detail = await api(`/api/history/${h.id}`);
      document.getElementById("methodSelect").value = detail.method;
      document.getElementById("urlInput").value = detail.url;
      document.getElementById("responseOutput").textContent = detail.response.body_text || "";
      document.getElementById("statusBadge").textContent = `Status: ${detail.status_code}`;
      document.getElementById("latencyBadge").textContent = `${detail.elapsed_ms} ms`;
      document.getElementById("sizeBadge").textContent = `${detail.size_bytes} B`;
    };
    container.appendChild(item);
  }
}

async function sendCurrentRequest(previewOnly = false) {
  const method = document.getElementById("methodSelect").value;
  const raw_url = document.getElementById("urlInput").value.trim();
  const query_params = parseJsonSafe(document.getElementById("paramsInput").value, []);
  const headers = parseJsonSafe(document.getElementById("headersInput").value, []);
  const body = buildCurrentBody();
  const auth = buildCurrentAuth();
  const environment_id = document.getElementById("envSelect").value || null;

  const endpoint = previewOnly ? "/api/requests/interpolate" : "/api/requests/send";
  document.getElementById("statusBadge").textContent = previewOnly ? "Interpolating..." : "Sending...";

  try {
    const res = await api(endpoint, {
      method: "POST",
      body: JSON.stringify({
        method,
        raw_url,
        query_params,
        headers,
        body,
        auth,
        collection_id: state.activeCollectionId,
        request_id: state.activeRequestId,
        environment_id,
      }),
    });

    if (previewOnly) {
      document.getElementById("statusBadge").textContent = "Interpolated Preview";
      document.getElementById("responseOutput").textContent = JSON.stringify(res, null, 2);
      return;
    }

    document.getElementById("statusBadge").textContent = `${res.status_code} ${res.reason_phrase || ""}`;
    document.getElementById("latencyBadge").textContent = `${res.elapsed_ms} ms`;
    document.getElementById("sizeBadge").textContent = `${res.size_bytes} B`;
    document.getElementById("responseOutput").textContent =
      res.body_json ? JSON.stringify(res.body_json, null, 2) : (res.body_text || res.error || "");
    await loadHistory();
  } catch (err) {
    document.getElementById("statusBadge").textContent = "Request Error";
    document.getElementById("responseOutput").textContent = err && err.message ? err.message : String(err);
  }
}

function wireEvents() {
  document.getElementById("sendBtn").onclick = () => sendCurrentRequest(false);
  document.getElementById("previewBtn").onclick = () => sendCurrentRequest(true);

  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.onclick = () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-content").forEach((c) => c.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById(btn.dataset.tab).classList.add("active");
    };
  });

  document.querySelectorAll(".sidebar-tab").forEach((btn) => {
    btn.onclick = () => {
      document.querySelectorAll(".sidebar-tab").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".sidebar-pane").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById(`${btn.dataset.sidebar}Pane`).classList.add("active");
    };
  });

  document.getElementById("importBtn").onclick = () => {
    document.getElementById("importFileInput").click();
  };

  document.getElementById("importFileInput").onchange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      const text = await file.text();
      await api("/api/collections/import", {
        method: "POST",
        body: JSON.stringify({ collection_json: JSON.parse(text) }),
      });
      await loadCollections();
    } catch (err) {
      document.getElementById("statusBadge").textContent = "Import Error";
      document.getElementById("responseOutput").textContent = err && err.message ? err.message : String(err);
    } finally {
      e.target.value = "";
    }
  };

  document.getElementById("newCollectionBtn").onclick = async () => {
    const name = prompt("Collection Name:", "New OpenPost Collection");
    if (!name) return;
    const created = await api("/api/collections", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    state.activeCollectionId = created.id;
    state.activeRequestId = null;
    await loadCollections();
  };

  document.getElementById("saveRequestBtn").onclick = async () => {
    if (!state.activeCollectionId) {
      const created = await api("/api/collections", {
        method: "POST",
        body: JSON.stringify({ name: "Scratch Pad Collection" }),
      });
      state.activeCollectionId = created.id;
    }
    const name = prompt("Request Name:", "Saved Request");
    if (!name) return;
    await api(`/api/collections/${state.activeCollectionId}/requests`, {
      method: "POST",
      body: JSON.stringify({
        request_id: state.activeRequestId,
        name,
        method: document.getElementById("methodSelect").value,
        raw_url: document.getElementById("urlInput").value.trim(),
        query_params: parseJsonSafe(document.getElementById("paramsInput").value, []),
        headers: parseJsonSafe(document.getElementById("headersInput").value, []),
        body: buildCurrentBody(),
        auth: buildCurrentAuth(),
      }),
    });
    await loadCollections();
  };

  document.getElementById("manageEnvBtn").onclick = async () => {
    const name = prompt("Environment Name (e.g., Local Dev):", "Local Dev");
    if (!name) return;
    const rawVars = prompt(
      'Enter variables as JSON object (e.g. {"base_url": "https://httpbin.org"}):',
      '{"base_url": "https://httpbin.org"}'
    );
    if (!rawVars) return;
    try {
      const parsedVars = JSON.parse(rawVars);
      const env = await api("/api/environments", {
        method: "POST",
        body: JSON.stringify({ name, variables: parsedVars }),
      });
      await loadEnvironments();
      document.getElementById("envSelect").value = env.id;
    } catch (err) {
      document.getElementById("statusBadge").textContent = "Environment Error";
      document.getElementById("responseOutput").textContent = err && err.message ? err.message : String(err);
    }
  };

  document.getElementById("clearHistoryBtn").onclick = async () => {
    await api("/api/history", { method: "DELETE" });
    await loadHistory();
  };

  window.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
      e.preventDefault();
      document.getElementById("saveRequestBtn").click();
    }
  });
}

(async function init() {
  wireEvents();
  try {
    await Promise.all([
      refreshSandboxStatus(),
      loadEnvironments(),
      loadCollections(),
      loadHistory(),
    ]);
  } catch {
    // Handled by refreshSandboxStatus
  }
})();
