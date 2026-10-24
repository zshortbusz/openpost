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
  if (type === "noauth" || !val) return { type: "noauth", params: {} };
  if (type === "bearer") return { type: "bearer", params: { token: val } };
  if (type === "apikey") return { type: "apikey", params: { key: "X-API-Key", value: val, in: "header" } };
  if (type === "basic") {
    const [username, password = ""] = val.split(":");
    return { type: "basic", params: { username, password } };
  }
  return null;
}

async function refreshSandboxStatus() {
  const badge = document.getElementById("sandboxBadge");
  if (badge) {
    badge.textContent = "Clean-Room: 100% Local";
    badge.style.borderColor = "#10b981";
    badge.style.color = "#10b981";
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
    header.innerHTML = `<span>📁 ${colDetail.name}</span><span style="color:#8b95a7">${colDetail.requests.length}</span>`;
    header.onclick = () => {
      state.activeCollectionId = colDetail.id;
      document.getElementById("activeReqLabel").textContent = `Collection: ${colDetail.name}`;
    };
    container.appendChild(header);

    for (const req of colDetail.requests) {
      const item = document.createElement("div");
      item.className = "tree-item";
      item.style.paddingLeft = "22px";
      const folderPrefix = req.folder_path && req.folder_path.length ? `${req.folder_path.join("/")}/ ` : "";
      item.innerHTML = `
        <span>
          <span class="method-tag method-${req.method}">${req.method}</span>
          ${folderPrefix}${req.name}
        </span>
      `;
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
  document.getElementById("bodyInput").value = req.body && req.body.raw ? req.body.raw : "";
  document.getElementById("activeReqLabel").textContent = `${req.name} (${req.id.slice(0, 8)})`;
}

async function loadHistory() {
  const history = await api("/api/history?limit=40");
  const container = document.getElementById("historyList");
  container.innerHTML = "";
  for (const h of history) {
    const item = document.createElement("div");
    item.className = "tree-item";
    item.innerHTML = `
      <span><span class="method-tag method-${h.method}">${h.method}</span>${h.url.slice(0, 28)}</span>
      <span style="color:#8b95a7">${h.status_code}</span>
    `;
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
  const rawBody = document.getElementById("bodyInput").value;
  const body = rawBody.trim() ? { mode: "raw", raw: rawBody, language: "json" } : null;
  const auth = buildCurrentAuth();
  const environment_id = document.getElementById("envSelect").value || null;

  const endpoint = previewOnly ? "/api/requests/interpolate" : "/api/requests/send";
  document.getElementById("statusBadge").textContent = previewOnly ? "Interpolating..." : "Sending...";

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
    const text = await file.text();
    await api("/api/collections/import", {
      method: "POST",
      body: JSON.stringify({ collection_json: JSON.parse(text) }),
    });
    await loadCollections();
  };

  document.getElementById("newCollectionBtn").onclick = async () => {
    const name = prompt("Collection Name:", "New OpenPost Collection");
    if (!name) return;
    const created = await api("/api/collections", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    state.activeCollectionId = created.id;
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
    const rawBody = document.getElementById("bodyInput").value;
    await api(`/api/collections/${state.activeCollectionId}/requests`, {
      method: "POST",
      body: JSON.stringify({
        request_id: state.activeRequestId,
        name,
        method: document.getElementById("methodSelect").value,
        raw_url: document.getElementById("urlInput").value.trim(),
        query_params: parseJsonSafe(document.getElementById("paramsInput").value, []),
        headers: parseJsonSafe(document.getElementById("headersInput").value, []),
        body: rawBody.trim() ? { mode: "raw", raw: rawBody, language: "json" } : null,
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
    const env = await api("/api/environments", {
      method: "POST",
      body: JSON.stringify({ name, variables: JSON.parse(rawVars) }),
    });
    await loadEnvironments();
    document.getElementById("envSelect").value = env.id;
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
  await Promise.all([
    refreshSandboxStatus(),
    loadEnvironments(),
    loadCollections(),
    loadHistory(),
  ]);
})();
