import { loadOverview } from "./api.js";

const byId = (id) => document.getElementById(id);
const refreshButton = byId("refreshStatus");
const toast = byId("toast");
let activeController = null;

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
refreshOverview();
