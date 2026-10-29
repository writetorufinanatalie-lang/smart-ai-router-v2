import { loadOverview, routeRequest } from "./api.js";

const byId = (id) => document.getElementById(id);
const refreshButton = byId("refreshStatus");
const toast = byId("toast");
let activeController = null;
let playgroundBusy = false;
let sessionItems = 0;

function setText(id, value) {
  byId(id).textContent = value == null ? "—" : String(value);
}

function setStatus(lightId, titleId, label, state) {
  const light = byId(lightId);
  light.dataset.state = state;
  setText(titleId, label);
}

function showToast(message) {
  toast.textContent = message;
  toast.hidden = false;
  window.clearTimeout(showToast.timeoutId);
  showToast.timeoutId = window.setTimeout(() => {
    toast.hidden = true;
  }, 3500);
}

function displayBackendUnavailable() {
  byId("connectionPill").dataset.state = "error";
  setText("connectionText", "Backend unavailable");
  setStatus("backendLight", "backendStatus", "Disconnected", "error");
  setText("backendDetail", "Start FastAPI, then refresh this page.");
  setText("metricsStatus", "Unavailable");
  setStatus("modelLight", "modelStatus", "Unavailable", "error");
  setText("modelDetail", "Backend health could not be read.");
  setText("modelName", "—");
  setStatus("cloudLight", "cloudStatus", "Unavailable", "unknown");
  setText("cloudDetail", "Backend configuration could not be read.");
  setText("providerStatus", "Unavailable");
  setStatus("deviceLight", "deviceCount", "Unavailable", "unknown");
  setText("deviceDetail", "Backend device state could not be read.");
  setText("deviceStatusNote", "Device state unavailable until the backend responds.");
  byId("deviceList").replaceChildren();
  setText("normalRequests", "—");
  setText("evaluationCases", "—");
  setText("localCount", "—");
  setText("cloudCount", "—");
  setText("commandCount", "—");
  setText("clarificationCount", "—");
}

function displayStatsUnavailable() {
  for (const id of ["normalRequests", "evaluationCases", "localCount", "cloudCount", "commandCount", "clarificationCount"]) {
    setText(id, "Unavailable");
  }
}

function displayDevicesUnavailable() {
  setStatus("deviceLight", "deviceCount", "Unavailable", "unknown");
  setText("deviceDetail", "Device status could not be read.");
  setText("deviceStatusNote", "Simulated device state is unavailable.");
  byId("deviceList").replaceChildren();
}

function applyHealth(payload) {
  const backend = payload.backend ?? {};
  const ollama = payload.ollama ?? {};
  const cloud = payload.cloud ?? {};
  const backendReady = backend.status === "ok";
  byId("connectionPill").dataset.state = backendReady ? "online" : "error";
  setText("connectionText", backendReady ? "Backend connected" : "Backend degraded");
  setStatus(
    "backendLight",
    "backendStatus",
    backendReady ? "Connected" : "Unavailable",
    backendReady ? "online" : "error",
  );
  setText("backendDetail", backendReady ? "FastAPI is responding." : "The backend or metrics store is unavailable.");
  setText("metricsStatus", backend.metrics_store_available ? "Connected" : "Unavailable");

  const ollamaAvailable = ollama.service_available === true;
  const modelAvailable = ollama.model_available === true;
  const modelLabel = modelAvailable ? "Available" : ollamaAvailable ? "Model missing" : "Disconnected";
  const modelState = modelAvailable ? "online" : "error";
  setStatus("modelLight", "modelStatus", modelLabel, modelState);
  setText(
    "modelDetail",
    ollamaAvailable
      ? modelAvailable
        ? "Ollama is connected and the selected model is installed."
        : "Ollama is connected, but the selected model is not installed."
      : "Ollama did not respond to the local health check.",
  );
  setText("modelName", ollama.model ?? "Unavailable");
  setText("footerModel", ollama.model ?? "model unavailable");

  const cloudConfigured = cloud.configured === true;
  setStatus(
    "cloudLight",
    "cloudStatus",
    cloudConfigured ? "Configured" : "Not configured",
    cloudConfigured ? "online" : "muted",
  );
  setText(
    "cloudDetail",
    cloudConfigured
      ? "Cloud configuration is present; requests leave this machine only when routed there."
      : "No provider is configured. Cloud requests cannot be processed.",
  );
  setText(
    "providerStatus",
    cloud.provider_configured ? "Configured" : "Not configured",
  );
}

function applyStats(payload) {
  setText("normalRequests", payload.normal_user_requests ?? payload.total_requests ?? 0);
  setText("evaluationCases", payload.evaluation_cases ?? 0);
  const routes = payload.route_counts ?? {};
  setText("localCount", routes.LOCAL ?? 0);
  setText("cloudCount", routes.CLOUD ?? 0);
  setText("commandCount", (routes.COMMAND ?? 0) + (routes.COMMAND_UNSUPPORTED ?? 0));
  setText("clarificationCount", routes.CLARIFICATION ?? 0);
}

function createDeviceRow(name, state) {
  const row = document.createElement("div");
  row.className = "device-row";
  const details = document.createElement("div");
  details.className = "device-name";
  const dot = document.createElement("span");
  dot.className = "device-state-dot";
  dot.dataset.on = state.on === true ? "true" : "false";
  dot.setAttribute("aria-hidden", "true");
  const label = document.createElement("strong");
  label.textContent = name.replaceAll("_", " ");
  details.append(dot, label);

  const value = document.createElement("span");
  value.className = "device-state-value";
  if (typeof state.on === "boolean") {
    value.textContent = state.on ? "On" : "Off";
  } else if (typeof state.level === "number") {
    value.textContent = `Level ${state.level}%`;
  } else {
    value.textContent = "State available";
  }

  const subvalue = document.createElement("span");
  subvalue.className = "device-subvalue";
  if (typeof state.brightness === "number") subvalue.textContent = `Brightness ${state.brightness}%`;
  else if (typeof state.speed === "number") subvalue.textContent = `Speed ${state.speed}%`;
  else subvalue.textContent = "";

  row.append(details, value, subvalue);
  return row;
}

function applyDevices(payload) {
  const devices = payload.devices ?? {};
  const entries = Object.entries(devices);
  setStatus("deviceLight", "deviceCount", `${entries.length} simulated`, "online");
  setText("deviceDetail", "Current in-memory registry snapshot");
  setText("deviceStatusNote", payload.status ?? "Simulated device state");
  const list = byId("deviceList");
  list.replaceChildren();
  for (const [name, state] of entries) list.append(createDeviceRow(name, state));
  if (entries.length === 0) {
    const empty = document.createElement("div");
    empty.className = "device-placeholder";
    empty.textContent = "No simulated devices are available.";
    list.append(empty);
  }
}

function applyUnavailable(promiseResult, apply, fallbackMessage) {
  if (promiseResult.status === "fulfilled") {
    apply(promiseResult.value);
    return true;
  }
  showToast(fallbackMessage);
  return false;
}

async function refreshOverview() {
  if (activeController) activeController.abort();
  const controller = new AbortController();
  activeController = controller;
  refreshButton.disabled = true;
  refreshButton.classList.add("is-loading");
  byId("connectionPill").dataset.state = "checking";
  setText("connectionText", "Checking backend");
  setStatus("backendLight", "backendStatus", "Checking", "checking");
  setStatus("modelLight", "modelStatus", "Checking", "checking");
  setStatus("cloudLight", "cloudStatus", "Checking", "checking");
  setStatus("deviceLight", "deviceCount", "Checking", "checking");

  try {
    const result = await loadOverview(controller.signal);
    if (controller.signal.aborted) return;
    if (result.health.status === "fulfilled") {
      applyHealth(result.health.value);
      if (!applyUnavailable(result.stats, applyStats, "Request metrics are unavailable.")) {
        displayStatsUnavailable();
      }
      if (!applyUnavailable(result.devices, applyDevices, "Simulated device state is unavailable.")) {
        displayDevicesUnavailable();
      }
    } else {
      displayBackendUnavailable();
      showToast("The backend could not be reached. Start FastAPI, then refresh.");
    }
    setText("lastChecked", new Date().toLocaleTimeString());
  } catch (error) {
    if (error.name !== "AbortError" && !controller.signal.aborted) {
      displayBackendUnavailable();
      showToast(error.message || "Status refresh failed.");
    }
  } finally {
    if (activeController === controller) {
      refreshButton.disabled = false;
      refreshButton.classList.remove("is-loading");
    }
  }
}

refreshButton.addEventListener("click", refreshOverview);

function switchView(name) {
  const overview = name === "overview";
  byId("overviewView").hidden = !overview;
  byId("playgroundView").hidden = overview;
  for (const button of document.querySelectorAll("[data-view-button]")) {
    const selected = button.dataset.viewButton === name;
    button.classList.toggle("is-active", selected);
    if (selected) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
    const indicator = button.querySelector(".nav-indicator");
    if (indicator) indicator.hidden = !selected;
  }
  document.querySelector(".breadcrumbs strong").textContent = overview ? "OVERVIEW" : "AI PLAYGROUND";
  document.title = `Smart AI Router · ${overview ? "Overview" : "AI Playground"}`;
}

for (const button of document.querySelectorAll("[data-view-button]")) {
  button.addEventListener("click", () => switchView(button.dataset.viewButton));
}

const requestForm = byId("requestForm");
const requestInput = byId("requestInput");
const sendButton = byId("sendRequest");
const sessionLog = byId("sessionLog");
const playgroundStatus = byId("playgroundStatus");

function updateComposer() {
  byId("characterCount").textContent = String(requestInput.value.length);
  sendButton.disabled = playgroundBusy || requestInput.value.trim().length === 0;
}

requestInput.addEventListener("input", updateComposer);
for (const example of document.querySelectorAll("[data-example]")) {
  example.addEventListener("click", () => {
    requestInput.value = example.dataset.example;
    updateComposer();
    requestInput.focus();
  });
}

function addText(parent, tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = value;
  parent.append(node);
  return node;
}

function addMetaGrid(card, payload) {
  const grid = document.createElement("dl");
  grid.className = "result-meta";
  const values = [
    ["Classifier label", payload.classifier_label ?? "Unavailable"],
    ["Final route", payload.final_route ?? "ERROR"],
    ["Parser override", payload.rule_parser_overrode_classifier ? "Yes" : "No"],
    ["Classification", formatLatency(payload.classification_latency_ms)],
    ["Answer generation", formatLatency(payload.answer_generation_latency_ms)],
    ["Cloud", formatLatency(payload.cloud_latency_ms)],
    ["Processing location", payload.classification_location ?? "Unavailable"],
    ["Cloud contacted", payload.request_sent_to_cloud === true ? "Yes" : "No"],
  ];
  for (const [label, value] of values) {
    const item = document.createElement("div");
    item.className = "result-meta-item";
    addText(item, "dt", "", label);
    addText(item, "dd", "", value);
    grid.append(item);
  }
  card.append(grid);
}

function formatLatency(value) {
  return typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(1)} ms` : "Not run";
}

function renderResult(requestText, payload, failureMessage = null) {
  byId("sessionEmpty")?.remove();
  const card = document.createElement("article");
  card.className = "result-card";
  card.setAttribute("aria-label", "Router response");
  const header = document.createElement("div");
  header.className = "result-card-header";
  const executionStatus = payload.execution_status ?? "";
  const isClarification = payload.final_route === "CLARIFICATION";
  const noDevice = executionStatus === "device_control_not_performed";
  const title = failureMessage ? "Request failed" : isClarification ? "Request needs clarification" : noDevice ? "No device was controlled" : payload.privacy_blocked ? "Blocked by Privacy Shield" : payload.execution_status === "local_generation_failed" ? "Local answer unavailable" : payload.message || "Router response";
  addText(header, "strong", "result-title", title);
  addText(header, "span", `route-badge route-${String(payload.final_route ?? "error").toLowerCase()}`, payload.final_route ?? "ERROR");
  card.append(header);
  addText(card, "p", "submitted-request", requestText);

  if (failureMessage) addText(card, "p", "result-message result-error", failureMessage);
  else if (payload.message) addText(card, "p", "result-message", payload.message);
  if (isClarification) addText(card, "p", "clarification-hint", "Edit the request above and resend when you are ready.");
  if (noDevice) addText(card, "p", "result-hint", "This request was not recognized as an allowed device command. No device action was run.");

  if (payload.answer) {
    addText(card, "div", "answer-label", "RESPONSE");
    addText(card, "p", "answer-copy", payload.answer);
  }
  if (payload.command_result) {
    addText(card, "div", "answer-label", "SIMULATED COMMAND RESULT");
    addText(card, "pre", "command-output", JSON.stringify(payload.command_result, null, 2));
  }
  if (payload.privacy_blocked && Array.isArray(payload.sensitive_data_types) && payload.sensitive_data_types.length) {
    addText(card, "p", "privacy-types", `Detected types: ${payload.sensitive_data_types.join(", ")}. Sensitive values are not displayed here.`);
  }
  const reason = payload.classification_reason;
  if (reason) {
    const source = payload.classification_reason_source === "rule" ? "Rule-based explanation" : payload.classification_reason_source === "model" ? "Model reason · unverified" : "Classification explanation";
    addText(card, "div", "answer-label", source);
    addText(card, "p", "reason-copy", reason);
  }
  addMetaGrid(card, payload);
  sessionLog.append(card);
  card.scrollIntoView({ block: "nearest", behavior: "smooth" });
  sessionItems += 1;
  playgroundStatus.textContent = isClarification ? "Request needs clarification. Edit it and resend." : title;
}

requestForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const requestText = requestInput.value.trim();
  if (!requestText || playgroundBusy) return;
  playgroundBusy = true;
  updateComposer();
  sendButton.querySelector("span:first-child").textContent = "Sending…";
  playgroundStatus.textContent = "Waiting for the local router response.";
  const pending = document.createElement("div");
  pending.className = "pending-request";
  pending.setAttribute("role", "status");
  pending.textContent = "Waiting for the backend response…";
  sessionLog.append(pending);
  pending.scrollIntoView({ block: "nearest" });
  try {
    const payload = await routeRequest(requestText);
    pending.remove();
    renderResult(requestText, payload);
  } catch (error) {
    pending.remove();
    renderResult(requestText, { final_route: "ERROR", execution_status: "request_failed" }, error.message || "The router request failed.");
  } finally {
    playgroundBusy = false;
    sendButton.querySelector("span:first-child").textContent = "Send request";
    updateComposer();
  }
});

byId("clearSession").addEventListener("click", () => {
  sessionLog.replaceChildren();
  const empty = document.createElement("div");
  empty.className = "session-empty";
  empty.id = "sessionEmpty";
  addText(empty, "span", "empty-mark", "⌘").setAttribute("aria-hidden", "true");
  addText(empty, "strong", "", "Your session is ready");
  addText(empty, "span", "", "Choose an example or write a request below.");
  sessionLog.append(empty);
  sessionItems = 0;
  playgroundStatus.textContent = "Session cleared.";
});

updateComposer();
refreshOverview();
