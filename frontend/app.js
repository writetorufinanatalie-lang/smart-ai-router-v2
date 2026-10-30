import { getEvaluationRun, loadEvaluationReports, loadOverview, routeRequest, startEvaluationRun } from "./api.js";

const byId = (id) => document.getElementById(id);
const refreshButton = byId("refreshStatus");
const toast = byId("toast");
let activeController = null;
let playgroundBusy = false;
let sessionItems = 0;
let latestRouteResult = null;
let activeEvaluationRunId = null;
let activeEvaluationSuiteId = null;
let evaluationRunStarting = false;
const SVG_NS = "http://www.w3.org/2000/svg";
const themeToggle = byId("themeToggle");

function applyTheme(theme, persist = false) {
  const normalizedTheme = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = normalizedTheme;
  const nextTheme = normalizedTheme === "dark" ? "light" : "dark";
  themeToggle.setAttribute("aria-label", `Switch to ${nextTheme} theme`);
  themeToggle.setAttribute("title", `Switch to ${nextTheme} theme`);
  themeToggle.setAttribute("aria-pressed", String(normalizedTheme === "light"));
  themeToggle.querySelector("span").textContent = `${nextTheme[0].toUpperCase()}${nextTheme.slice(1)} theme`;
  byId("themeColorMeta").content = getComputedStyle(document.documentElement).getPropertyValue("--theme-color-meta").trim();
  if (persist) {
    try {
      localStorage.setItem("smart-router-theme", normalizedTheme);
    } catch (_) {
      // The selected theme remains active for this page even when storage is blocked.
    }
  }
}

applyTheme(document.documentElement.dataset.theme || "dark");
themeToggle.addEventListener("click", () => {
  applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark", true);
});

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
  displayHealthUnavailable();
  setText("normalRequests", "—");
  setText("evaluationCases", "—");
  setText("localCount", "—");
  setText("cloudCount", "—");
  setText("commandCount", "—");
  setText("clarificationCount", "—");
  showUnavailableAnalytics("Backend data unavailable.");
  displayPrivacyHistoryUnavailable();
}

function displayHealthUnavailable() {
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
  displayPrivacyHealthUnavailable();
}

function displayStatsUnavailable() {
  for (const id of ["normalRequests", "evaluationCases", "localCount", "cloudCount", "commandCount", "clarificationCount"]) {
    setText(id, "Unavailable");
  }
  for (const id of ["overviewCategories", "overviewCommandOutcomes", "analyticsCategories", "analyticsCommandOutcomes", "routeDistributionChart", "latencySummary"]) {
    showEmptyState(id, "Request metrics unavailable.");
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
  applyPrivacyHealth(payload);
}

function setPrivacyStatus(lightId, titleId, detailId, label, state, detail) {
  setStatus(lightId, titleId, label, state);
  setText(detailId, detail);
}

function applyPrivacyHealth(payload) {
  const backend = payload.backend ?? {};
  const ollama = payload.ollama ?? {};
  const cloud = payload.cloud ?? {};
  const backendConnected = backend.status === "ok";
  setPrivacyStatus(
    "privacyBackendLight", "privacyBackendStatus", "privacyBackendDetail",
    backendConnected ? "Connected" : "Disconnected",
    backendConnected ? "online" : "error",
    backendConnected ? "FastAPI returned backend status ok." : "FastAPI reports that the backend or its storage is unavailable.",
  );

  const runtimeConnected = ollama.service_available === true;
  setPrivacyStatus(
    "privacyOllamaLight", "privacyOllamaStatus", "privacyOllamaDetail",
    runtimeConnected ? "Connected" : "Disconnected",
    runtimeConnected ? "online" : "error",
    runtimeConnected ? "Ollama responded to the local health check." : "Ollama did not respond to the local health check.",
  );

  const modelConnected = ollama.model_available === true;
  const modelStatus = modelConnected ? "Connected" : runtimeConnected ? "Not configured" : "Disconnected";
  const modelState = modelConnected ? "online" : runtimeConnected ? "muted" : "error";
  setPrivacyStatus(
    "privacyModelLight", "privacyModelStatus", "privacyModelDetail",
    modelStatus, modelState,
    modelConnected ? "The selected local model is installed and available." : runtimeConnected ? "Ollama is responding, but the selected model is not installed." : "Model availability cannot be confirmed while Ollama is disconnected.",
  );
  setText("privacyModelName", ollama.model ?? "Unavailable");

  const cloudConfigured = cloud.configured === true;
  setPrivacyStatus(
    "privacyCloudLight", "privacyCloudStatus", "privacyCloudDetail",
    cloudConfigured ? "Connected" : "Not configured",
    cloudConfigured ? "online" : "muted",
    cloudConfigured
      ? "Required provider configuration is present; /health does not test provider connectivity."
      : "Required cloud configuration is incomplete; cloud requests cannot currently be processed.",
  );

  const metricsConnected = backend.metrics_store_available === true;
  setPrivacyStatus(
    "privacyMetricsLight", "privacyMetricsStatus", "privacyMetricsDetail",
    metricsConnected ? "Connected" : "Disconnected",
    metricsConnected ? "online" : "error",
    metricsConnected ? "The backend reports its metrics store is available." : "The backend reports its metrics store is unavailable.",
  );
  setText("privacyLastChecked", new Date().toLocaleTimeString());
}

function displayPrivacyHealthUnavailable() {
  const unavailable = "Could not read /health; this status is unavailable.";
  setText("privacyLastChecked", new Date().toLocaleTimeString());
  setPrivacyStatus("privacyBackendLight", "privacyBackendStatus", "privacyBackendDetail", "Disconnected", "error", unavailable);
  setPrivacyStatus("privacyOllamaLight", "privacyOllamaStatus", "privacyOllamaDetail", "Disconnected", "error", unavailable);
  setPrivacyStatus("privacyModelLight", "privacyModelStatus", "privacyModelDetail", "Disconnected", "error", unavailable);
  setText("privacyModelName", "Unavailable");
  setPrivacyStatus("privacyCloudLight", "privacyCloudStatus", "privacyCloudDetail", "Disconnected", "error", "Cloud configuration could not be read from /health.");
  setPrivacyStatus("privacyMetricsLight", "privacyMetricsStatus", "privacyMetricsDetail", "Disconnected", "error", unavailable);
}

function applyStats(payload) {
  setText("normalRequests", payload.normal_user_requests ?? payload.total_requests ?? 0);
  setText("evaluationCases", payload.evaluation_cases ?? 0);
  const routes = payload.route_counts ?? {};
  setText("localCount", routes.LOCAL ?? 0);
  setText("cloudCount", routes.CLOUD ?? 0);
  setText("commandCount", (routes.COMMAND ?? 0) + (routes.COMMAND_UNSUPPORTED ?? 0));
  setText("clarificationCount", routes.CLARIFICATION ?? 0);
  renderCategorySummary("overviewCategories", payload.classifier_label_counts ?? {}, payload.total_requests ?? 0);
  renderCategorySummary("analyticsCategories", payload.classifier_label_counts ?? {}, payload.total_requests ?? 0);
  renderCommandOutcomes("overviewCommandOutcomes", payload.execution_status_counts ?? {}, payload.total_requests ?? 0);
  renderCommandOutcomes("analyticsCommandOutcomes", payload.execution_status_counts ?? {}, payload.total_requests ?? 0);
  renderRouteDistribution(payload.route_counts ?? {});
  renderLatencySummary(payload);
}

function showEmptyState(id, message) {
  const host = byId(id);
  if (!host) return;
  const empty = document.createElement("p");
  empty.className = "empty-state";
  empty.textContent = message;
  host.replaceChildren(empty);
}

function renderSummaryRows(hostId, entries, hasData) {
  const host = byId(hostId);
  host.replaceChildren();
  if (!hasData) {
    showEmptyState(hostId, "No data yet.");
    return;
  }
  for (const [label, count] of entries) {
    const row = document.createElement("div");
    row.className = "summary-row";
    const name = document.createElement("span");
    name.textContent = label;
    const value = document.createElement("strong");
    value.textContent = String(count);
    row.append(name, value);
    host.append(row);
  }
}

function renderCategorySummary(hostId, counts, totalRequests) {
  const entries = ["SIMPLE", "COMPLEX", "COMMAND"].map((label) => [label, Number(counts[label] ?? 0)]);
  renderSummaryRows(hostId, entries, Number(totalRequests) > 0);
}

function renderCommandOutcomes(hostId, counts, totalRequests) {
  const labels = {
    executed_locally: "Simulated command executed",
    device_not_supported: "Device not supported",
    command_not_supported: "Command not supported",
    device_control_not_performed: "No device was controlled",
    clarification_needed: "Clarification requested",
  };
  const entries = Object.entries(labels).map(([key, label]) => [label, Number(counts[key] ?? 0)]);
  renderSummaryRows(hostId, entries, Number(totalRequests) > 0);
}

function svgElement(tag, attributes = {}, text = null) {
  const element = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, String(value));
  if (text !== null) element.textContent = String(text);
  return element;
}

function renderRouteDistribution(routeCounts) {
  const host = byId("routeDistributionChart");
  const entries = Object.entries(routeCounts).filter(([, value]) => Number(value) > 0).sort((a, b) => b[1] - a[1]);
  if (!entries.length) {
    showEmptyState("routeDistributionChart", "No data yet.");
    return;
  }
  const routeClasses = { LOCAL: "route-local", CLOUD: "route-cloud", COMMAND: "route-command", COMMAND_UNSUPPORTED: "route-unsupported", CLARIFICATION: "route-clarification", ERROR: "route-error" };
  const width = 660;
  const rowHeight = 39;
  const height = entries.length * rowHeight + 15;
  const svg = svgElement("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": "Route distribution from normal user requests" });
  svg.append(svgElement("title", {}, "Route distribution"));
  const maxValue = Math.max(...entries.map(([, value]) => Number(value)));
  entries.forEach(([route, rawCount], index) => {
    const count = Number(rawCount);
    const y = index * rowHeight + 5;
    svg.append(svgElement("text", { x: 0, y: y + 12, class: "chart-label" }, route.replaceAll("_", " ")));
    svg.append(svgElement("rect", { x: 174, y, width: 400, height: 18, rx: 5, class: "chart-track" }));
    svg.append(svgElement("rect", { x: 174, y, width: Math.max(2, 400 * count / maxValue), height: 18, rx: 5, class: `chart-bar ${routeClasses[route] ?? "route-error"}` }));
    svg.append(svgElement("text", { x: 590, y: y + 13, class: "chart-value" }, count));
  });
  host.replaceChildren(svg);
}

function renderDailyActivity(payload) {
  const days = payload.days ?? [];
  const host = byId("dailyActivityChart");
  if (!days.some((day) => Number(day.total_requests) > 0)) {
    showEmptyState("dailyActivityChart", "No data yet.");
    return;
  }
  const width = 660;
  const height = 260;
  const left = 42;
  const right = 16;
  const top = 16;
  const bottom = 40;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const maxValue = Math.max(1, ...days.map((day) => Number(day.total_requests) || 0));
  const scaleMax = Math.ceil(maxValue / 5) * 5 || 1;
  const svg = svgElement("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": "Daily normal user request activity" });
  svg.append(svgElement("title", {}, "Daily request activity"));
  const tickCount = Math.min(4, scaleMax);
  for (let tick = 0; tick <= tickCount; tick += 1) {
    const value = Math.round(scaleMax * tick / tickCount);
    const y = top + plotHeight - plotHeight * value / scaleMax;
    svg.append(svgElement("line", { x1: left, y1: y, x2: width - right, y2: y, class: "chart-gridline" }));
    svg.append(svgElement("text", { x: left - 10, y: y + 3, class: "chart-axis-label", "text-anchor": "end" }, value));
  }
  const pointFor = (day, index) => ({
    x: left + (days.length <= 1 ? plotWidth / 2 : plotWidth * index / (days.length - 1)),
    y: top + plotHeight - plotHeight * (Number(day.total_requests) || 0) / scaleMax,
  });
  const points = days.map(pointFor);
  const path = points.map((point, index) => `${index === 0 ? "M" : "L"}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
  svg.append(svgElement("path", { d: path, class: "chart-line" }));
  points.forEach((point) => svg.append(svgElement("circle", { cx: point.x, cy: point.y, r: 2.8, class: "chart-point" })));
  const dateIndices = [...new Set([0, Math.floor((days.length - 1) / 2), days.length - 1])];
  for (const index of dateIndices) {
    const point = points[index];
    const shortDate = String(days[index].date ?? "").slice(5);
    svg.append(svgElement("text", { x: point.x, y: height - 13, class: "chart-axis-label", "text-anchor": index === 0 ? "start" : index === days.length - 1 ? "end" : "middle" }, shortDate));
  }
  host.replaceChildren(svg);
}

function renderLatencySummary(stats) {
  const stages = [
    ["Classification", stats.average_classification_time_ms, stats.median_classification_time_ms],
    ["Answer generation", stats.average_answer_time_ms, stats.median_answer_time_ms],
    ["Cloud", stats.average_cloud_time_ms, stats.median_cloud_time_ms],
  ];
  const host = byId("latencySummary");
  host.replaceChildren();
  for (const [name, mean, median] of stages) {
    const card = document.createElement("div");
    card.className = "latency-stage";
    const title = document.createElement("strong");
    title.textContent = name;
    const meanRow = document.createElement("div");
    meanRow.className = "latency-value-row";
    meanRow.append(document.createElement("span"), document.createElement("b"));
    meanRow.firstChild.textContent = "Mean";
    meanRow.lastChild.textContent = formatLatency(mean);
    const medianRow = document.createElement("div");
    medianRow.className = "latency-value-row";
    medianRow.append(document.createElement("span"), document.createElement("b"));
    medianRow.firstChild.textContent = "Median";
    medianRow.lastChild.textContent = formatLatency(median);
    card.append(title, meanRow, medianRow);
    host.append(card);
  }
}

function formatTimestamp(value) {
  if (!value) return "Unavailable";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function renderHistory(payload) {
  const body = byId("historyRows");
  body.replaceChildren();
  const rows = payload.items ?? [];
  if (rows.length === 0) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.className = "table-empty";
    cell.colSpan = 7;
    cell.textContent = "No data yet.";
    row.append(cell);
    body.append(row);
    return;
  }
  for (const record of rows) {
    const row = document.createElement("tr");
    const values = [
      formatTimestamp(record.created_at),
      record.classifier_label ?? "Unavailable",
      record.final_route ?? "Unavailable",
      record.rule_parser_overrode_classifier ? "Yes" : "No",
      formatLatency(record.classification_time_ms),
      formatLatency(record.answer_time_ms),
      formatLatency(record.cloud_time_ms),
    ];
    for (const value of values) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    body.append(row);
  }
}

function renderPrivacyHistory(payload) {
  const body = byId("privacyHistoryRows");
  const rows = payload.items ?? [];
  const blockedCount = rows.filter((record) => record.privacy_blocked === true).length;
  const cloudHandoffCount = rows.filter((record) => record.request_sent_to_cloud === true).length;
  setText("privacyRequestsObserved", rows.length);
  setText("privacyBlockedCount", blockedCount);
  setText("privacyCloudHandoffCount", cloudHandoffCount);
  body.replaceChildren();
  if (rows.length === 0) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.className = "table-empty";
    cell.colSpan = 6;
    cell.textContent = "No data yet.";
    row.append(cell);
    body.append(row);
    return;
  }
  const typeLabels = {
    email: "Email pattern",
    phone_number: "Phone-number pattern",
    card_like_number: "Card-like number pattern",
  };
  for (const record of rows) {
    const detectedTypes = Array.isArray(record.sensitive_data_types) ? record.sensitive_data_types : [];
    const shieldResult = record.privacy_blocked === true
      ? "Blocked before cloud handoff"
      : detectedTypes.length > 0
        ? "Pattern recorded"
        : "No match recorded";
    const values = [
      formatTimestamp(record.created_at),
      record.classifier_label ?? "Unavailable",
      record.final_route ?? "Unavailable",
      shieldResult,
      detectedTypes.map((type) => typeLabels[type] ?? "Sensitive pattern").join(", ") || "None recorded",
      record.request_sent_to_cloud === true ? "Sent" : "Not sent",
    ];
    const row = document.createElement("tr");
    for (const value of values) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    body.append(row);
  }
}

function renderRequestHistory(payload) {
  renderHistory(payload);
  renderPrivacyHistory(payload);
}

function displayPrivacyHistoryUnavailable() {
  setText("privacyRequestsObserved", "Unavailable");
  setText("privacyBlockedCount", "Unavailable");
  setText("privacyCloudHandoffCount", "Unavailable");
  const body = byId("privacyHistoryRows");
  if (!body) return;
  const row = document.createElement("tr");
  const cell = document.createElement("td");
  cell.className = "table-empty";
  cell.colSpan = 6;
  cell.textContent = "Recent privacy metadata is unavailable.";
  row.append(cell);
  body.replaceChildren(row);
}

function showUnavailableAnalytics(message) {
  for (const id of ["overviewCategories", "overviewCommandOutcomes", "analyticsCategories", "analyticsCommandOutcomes", "dailyActivityChart", "routeDistributionChart", "latencySummary"]) {
    showEmptyState(id, message);
  }
  const body = byId("historyRows");
  if (body) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.className = "table-empty";
    cell.colSpan = 7;
    cell.textContent = message;
    row.append(cell);
    body.replaceChildren(row);
  }
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
    if (result.health.status === "fulfilled") applyHealth(result.health.value);
    else {
      displayHealthUnavailable();
      showToast("Backend health is unavailable; loading available dashboard data separately.");
    }
    if (!applyUnavailable(result.stats, applyStats, "Request metrics are unavailable.")) {
      displayStatsUnavailable();
    }
    if (!applyUnavailable(result.devices, applyDevices, "Simulated device state is unavailable.")) {
      displayDevicesUnavailable();
    }
    if (!applyUnavailable(result.history, renderRequestHistory, "Request history is unavailable.")) {
      const body = byId("historyRows");
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.className = "table-empty";
      cell.colSpan = 7;
      cell.textContent = "Request history is unavailable.";
      row.append(cell);
      body.replaceChildren(row);
      displayPrivacyHistoryUnavailable();
    }
    if (!applyUnavailable(result.activity, renderDailyActivity, "Daily activity is unavailable.")) {
      showEmptyState("dailyActivityChart", "Daily activity is unavailable.");
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
  const views = {
    overview: byId("overviewView"),
    playground: byId("playgroundView"),
    "live-routing": byId("liveRoutingView"),
    analytics: byId("analyticsView"),
    "test-lab": byId("testLabView"),
    privacy: byId("privacyView"),
  };
  const selectedView = views[name] ? name : "overview";
  for (const [viewName, view] of Object.entries(views)) view.hidden = viewName !== selectedView;
  for (const button of document.querySelectorAll("[data-view-button]")) {
    const selected = button.dataset.viewButton === selectedView;
    button.classList.toggle("is-active", selected);
    if (selected) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
    const indicator = button.querySelector(".nav-indicator");
    if (indicator) indicator.hidden = !selected;
  }
  const labels = { overview: "OVERVIEW", playground: "AI PLAYGROUND", "live-routing": "LIVE ROUTING", analytics: "ANALYTICS", "test-lab": "TEST LAB", privacy: "PRIVACY & SYSTEM" };
  const titles = { overview: "Overview", playground: "AI Playground", "live-routing": "Live Routing", analytics: "Analytics", "test-lab": "Test Lab", privacy: "Privacy & System" };
  document.querySelector(".breadcrumbs strong").textContent = labels[selectedView];
  document.title = `Smart AI Router · ${titles[selectedView]}`;
}

const testLabStatus = byId("testLabStatus");
const savedSuitesHost = byId("savedSuites");
const timestampedRunsHost = byId("timestampedRuns");
const refreshTestLabButton = byId("refreshTestLab");

function percentValue(value) {
  return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : "Not available";
}

function appendAccuracyCard(parent, title, value, correct, total, variant) {
  const card = document.createElement("div");
  card.className = `accuracy-card ${variant}`;
  const label = document.createElement("span");
  label.textContent = title;
  const score = document.createElement("strong");
  score.textContent = percentValue(value);
  const detail = document.createElement("small");
  detail.textContent = typeof correct === "number" && typeof total === "number" ? `${correct} / ${total} correct` : "No completed cases";
  card.append(label, score, detail);
  parent.append(card);
}

function renderReportSummary(summary) {
  const wrapper = document.createElement("div");
  wrapper.className = "report-summary";
  const accuracy = document.createElement("div");
  accuracy.className = "accuracy-pair";
  appendAccuracyCard(accuracy, "Classifier accuracy", summary?.classification_accuracy, summary?.classification_correct, summary?.cases_completed, "accuracy-classifier");
  appendAccuracyCard(accuracy, "Final-route accuracy", summary?.route_accuracy, summary?.route_correct, summary?.cases_completed, "accuracy-route");
  wrapper.append(accuracy);

  const categorySection = document.createElement("section");
  categorySection.className = "report-subsection";
  addText(categorySection, "h4", "", "Per-category precision and recall");
  const categoryData = summary?.per_category_precision_recall ?? {};
  const categoryRows = Object.entries(categoryData);
  if (categoryRows.length === 0) {
    addText(categorySection, "p", "report-empty", "No category metrics available yet.");
  } else {
    const table = document.createElement("table");
    table.className = "report-metric-table";
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    for (const title of ["Category", "Precision", "Recall", "Cases"]) addText(headRow, "th", "", title);
    head.append(headRow);
    const body = document.createElement("tbody");
    for (const [category, values] of categoryRows) {
      const row = document.createElement("tr");
      addText(row, "td", "", category);
      addText(row, "td", "", percentValue(values.precision));
      addText(row, "td", "", percentValue(values.recall));
      addText(row, "td", "", values.support ?? "Not available");
      body.append(row);
    }
    table.append(head, body);
    const metricsScroll = document.createElement("div");
    metricsScroll.className = "matrix-wrap";
    metricsScroll.tabIndex = 0;
    metricsScroll.setAttribute("role", "region");
    metricsScroll.setAttribute("aria-label", "Per-category metrics table; scroll horizontally to inspect all columns");
    metricsScroll.append(table);
    categorySection.append(metricsScroll);
  }
  wrapper.append(categorySection);

  const matrixSection = document.createElement("section");
  matrixSection.className = "report-subsection";
  addText(matrixSection, "h4", "", "Confusion matrix · expected rows, predicted columns");
  const matrixData = summary?.confusion_matrix;
  const labels = matrixData?.labels ?? [];
  if (!labels.length || !matrixData?.rows) {
    addText(matrixSection, "p", "report-empty", "No confusion matrix available yet.");
  } else {
    const matrix = document.createElement("div");
    matrix.className = "matrix-wrap";
    matrix.tabIndex = 0;
    matrix.setAttribute("role", "region");
    matrix.setAttribute("aria-label", "Confusion matrix; scroll horizontally to inspect all categories");
    const table = document.createElement("table");
    table.className = "confusion-table";
    const head = document.createElement("thead");
    const headerRow = document.createElement("tr");
    addText(headerRow, "th", "matrix-corner", "Expected ↓ / Predicted →");
    for (const label of labels) addText(headerRow, "th", "", label);
    head.append(headerRow);
    const body = document.createElement("tbody");
    for (const expected of Object.keys(matrixData.rows)) {
      const row = document.createElement("tr");
      addText(row, "th", "", expected);
      for (const predicted of labels) addText(row, "td", "", matrixData.rows[expected]?.[predicted] ?? "—");
      body.append(row);
    }
    table.append(head, body);
    matrix.append(table);
    matrixSection.append(matrix);
  }
  wrapper.append(matrixSection);
  return wrapper;
}

function renderCaseResults(container, results, filterId) {
  const section = document.createElement("section");
  section.className = "report-subsection case-results-section";
  const heading = document.createElement("div");
  heading.className = "case-results-heading";
  addText(heading, "h4", "", `Per-case results (${results.length})`);
  const select = document.createElement("select");
  select.className = "category-filter";
  select.id = filterId;
  select.setAttribute("aria-label", "Filter cases by expected category");
  const categories = [...new Set(results.map((item) => item.expected_category).filter(Boolean))].sort();
  const options = [["ALL", "All categories"], ...categories.map((category) => [category, category])];
  for (const [value, label] of options) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    select.append(option);
  }
  heading.append(select);
  section.append(heading);
  if (results.length === 0) {
    addText(section, "p", "report-empty", "No cases have completed yet.");
    container.append(section);
    return;
  }

  const scroll = document.createElement("div");
  scroll.className = "case-table-wrap";
  scroll.tabIndex = 0;
  scroll.setAttribute("role", "region");
  scroll.setAttribute("aria-label", "Evaluation case results; scroll horizontally to inspect all columns");
  const table = document.createElement("table");
  table.className = "case-table";
  const thead = document.createElement("thead");
  const headingRow = document.createElement("tr");
  for (const value of ["Case", "Expected category", "Predicted category", "Expected route", "Actual route", "Result", "Classification", "Answer", "Cloud"]) addText(headingRow, "th", "", value);
  thead.append(headingRow);
  const tbody = document.createElement("tbody");
  const rows = [];
  for (const item of results) {
    const row = document.createElement("tr");
    row.dataset.expectedCategory = item.expected_category ?? "UNKNOWN";
    const pass = item.classification_correct === true && item.route_correct === true;
    const values = [
      item.case_id ?? "Unavailable",
      item.expected_category ?? "Unavailable",
      item.predicted_category ?? "ERROR",
      item.expected_final_route ?? "Unavailable",
      item.actual_final_route ?? "Unavailable",
      pass ? "PASS" : "FAIL",
      formatLatency(item.classification_latency_ms),
      formatLatency(item.answer_latency_ms),
      formatLatency(item.cloud_latency_ms),
    ];
    values.forEach((value, index) => {
      const cell = document.createElement("td");
      cell.textContent = String(value);
      if (index === 5) cell.className = pass ? "case-pass" : "case-fail";
      row.append(cell);
    });
    tbody.append(row);
    rows.push(row);
  }
  table.append(thead, tbody);
  scroll.append(table);
  section.append(scroll);
  select.addEventListener("change", () => {
    const selected = select.value;
    for (const row of rows) row.hidden = selected !== "ALL" && row.dataset.expectedCategory !== selected;
  });
  container.append(section);
}

function buildSuitePanel({ suiteId, label, report, available = true, timestamped = false, file = null }) {
  const panel = document.createElement("article");
  panel.className = timestamped ? "panel test-report-card timestamped-report-card" : "panel test-report-card";
  const header = document.createElement("div");
  header.className = "test-report-header";
  const titleGroup = document.createElement("div");
  addText(titleGroup, "div", "eyebrow", timestamped ? "TIMESTAMPED RUN" : "SAVED REPORT");
  addText(titleGroup, "h3", "", label);
  if (file) addText(titleGroup, "p", "report-file", file);
  header.append(titleGroup);
  if (!timestamped && suiteId) {
    const runButton = document.createElement("button");
    runButton.type = "button";
    runButton.className = "send-button run-suite-button";
    runButton.dataset.suiteId = suiteId;
    runButton.textContent = "Run tests";
    runButton.disabled = Boolean(activeEvaluationSuiteId || evaluationRunStarting);
    runButton.addEventListener("click", () => startSuiteRun(suiteId));
    header.append(runButton);
  }
  panel.append(header);

  const progress = document.createElement("div");
  progress.className = "run-progress-host";
  if (!timestamped && suiteId) progress.id = `run-progress-${suiteId}`;
  panel.append(progress);

  if (!available || !report) {
    addText(panel, "p", "report-empty report-empty-panel", "No saved report available for this suite yet.");
    return panel;
  }
  const summary = report.summary ?? {};
  const status = report.run_status ?? "unknown";
  const reportInfo = document.createElement("div");
  reportInfo.className = "report-info-line";
  addText(reportInfo, "span", "", `Status: ${status.replaceAll("_", " ")}`);
  addText(reportInfo, "span", "", `${summary.cases_completed ?? report.results?.length ?? 0} / ${summary.cases_in_set ?? report.results?.length ?? "?"} cases`);
  panel.append(reportInfo, renderReportSummary(summary));
  const cases = Array.isArray(report.results) ? report.results : [];
  renderCaseResults(panel, cases, `filter-${timestamped ? file ?? suiteId : suiteId}`.replace(/[^a-zA-Z0-9_-]/g, "-"));
  return panel;
}

function renderTestLabReports(payload) {
  const fixed = Array.isArray(payload.sets) ? payload.sets : [];
  savedSuitesHost.replaceChildren();
  if (fixed.length === 0) addText(savedSuitesHost, "p", "empty-state", "No saved reports available.");
  for (const item of fixed) {
    savedSuitesHost.append(buildSuitePanel({
      suiteId: item.suite_id,
      label: item.label ?? item.suite_id ?? "Evaluation suite",
      report: item.report,
      available: item.available === true,
    }));
  }

  timestampedRunsHost.replaceChildren();
  const runs = Array.isArray(payload.timestamped_runs) ? payload.timestamped_runs : [];
  if (runs.length === 0) addText(timestampedRunsHost, "p", "empty-state", "No timestamped runs yet.");
  for (const item of runs) {
    const runLabel = `${item.label ?? item.suite_id ?? "Evaluation run"} · ${item.report?.finished_at ? formatTimestamp(item.report.finished_at) : item.file ?? "In progress"}`;
    timestampedRunsHost.append(buildSuitePanel({
      suiteId: null,
      label: runLabel,
      report: item.report,
      available: Boolean(item.report),
      timestamped: true,
      file: item.file,
    }));
  }
  setTestLabStatus(payload.note || "Saved reports loaded. Sets and runs are shown separately.");
  setRunButtonsDisabled(Boolean(activeEvaluationSuiteId || evaluationRunStarting));
}

function setTestLabStatus(message, isError = false) {
  testLabStatus.textContent = message;
  testLabStatus.dataset.state = isError ? "error" : "normal";
}

function setRunButtonsDisabled(disabled) {
  for (const button of document.querySelectorAll(".run-suite-button")) button.disabled = disabled;
}

function renderRunProgress(suiteId, job, message = null, error = false) {
  const host = byId(`run-progress-${suiteId}`);
  if (!host) return;
  host.replaceChildren();
  if (message) {
    addText(host, "p", error ? "run-error" : "run-message", message);
    return;
  }
  const total = Number(job.total_cases) || 0;
  const completed = Number(job.completed_cases) || 0;
  const percentage = total > 0 ? Math.min(100, Math.round(completed * 100 / total)) : 0;
  const progress = document.createElement("div");
  progress.className = "run-progress";
  const labelRow = document.createElement("div");
  labelRow.className = "run-progress-label";
  addText(labelRow, "span", "", job.status === "queued" ? "Queued" : `Running · ${completed} of ${total} cases`);
  addText(labelRow, "strong", "", `${percentage}%`);
  const bar = document.createElement("progress");
  bar.max = 100;
  bar.value = percentage;
  bar.setAttribute("aria-label", `Evaluation progress: ${completed} of ${total} cases`);
  progress.append(labelRow, bar);
  host.append(progress);
}

function delay(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

async function startSuiteRun(suiteId) {
  if (activeEvaluationSuiteId || evaluationRunStarting) return;
  evaluationRunStarting = true;
  activeEvaluationSuiteId = suiteId;
  setRunButtonsDisabled(true);
  setTestLabStatus("Starting the local evaluation. It may take a few minutes on this CPU-only laptop.");
  renderRunProgress(suiteId, { status: "queued", completed_cases: 0, total_cases: 0 });
  try {
    const job = await startEvaluationRun(suiteId);
    activeEvaluationRunId = job.run_id;
    evaluationRunStarting = false;
    renderRunProgress(suiteId, job);
    setTestLabStatus(`Evaluation started: ${job.suite_label ?? suiteId}. It may take a few minutes.`);
    await pollEvaluationRun(suiteId, job.run_id);
  } catch (error) {
    evaluationRunStarting = false;
    activeEvaluationRunId = null;
    activeEvaluationSuiteId = null;
    const message = error.status === 409
      ? "Another evaluation is already active on the backend. Wait for it to finish, then refresh Test Lab."
      : error.message || "Could not start the evaluation run.";
    renderRunProgress(suiteId, null, message, true);
    setTestLabStatus(message, true);
    setRunButtonsDisabled(false);
  }
}

async function pollEvaluationRun(suiteId, runId) {
  try {
    while (activeEvaluationRunId === runId) {
      await delay(1500);
      const job = await getEvaluationRun(runId);
      renderRunProgress(suiteId, job);
      if (job.status === "queued" || job.status === "running") continue;
      if (job.status === "failed") {
        const message = job.error || "Evaluation run failed. Check the backend log for details.";
        renderRunProgress(suiteId, null, message, true);
        setTestLabStatus(message, true);
      } else {
        renderRunProgress(suiteId, null, `Run finished: ${job.result_file ?? "timestamped report saved"}.`);
        setTestLabStatus(`Evaluation finished with status: ${String(job.status).replaceAll("_", " ")}.`);
      }
      activeEvaluationRunId = null;
      activeEvaluationSuiteId = null;
      setRunButtonsDisabled(false);
      await refreshTestLabReports(false);
      if (job.status === "failed") {
        const message = job.error || "Evaluation run failed. Check the backend log for details.";
        renderRunProgress(suiteId, null, message, true);
        setTestLabStatus(message, true);
      } else {
        setTestLabStatus(`Evaluation finished with status: ${String(job.status).replaceAll("_", " ")}.`);
      }
      return;
    }
  } catch (error) {
    activeEvaluationRunId = null;
    activeEvaluationSuiteId = null;
    setRunButtonsDisabled(false);
    const message = "Could not read evaluation progress. The backend may still be working; refresh Test Lab to check saved runs.";
    renderRunProgress(suiteId, null, message, true);
    setTestLabStatus(message, true);
    await refreshTestLabReports(false);
    renderRunProgress(suiteId, null, message, true);
    setTestLabStatus(message, true);
  }
}

async function refreshTestLabReports(announce = true) {
  refreshTestLabButton.disabled = true;
  try {
    const payload = await loadEvaluationReports();
    renderTestLabReports(payload);
    if (announce) setTestLabStatus("Saved reports and timestamped runs refreshed.");
  } catch (error) {
    savedSuitesHost.replaceChildren();
    timestampedRunsHost.replaceChildren();
    const unavailableMessage = error.status === 0
      ? "Backend disconnected. Saved evaluation reports could not be loaded."
      : `Test Lab reports are unavailable (HTTP ${error.status}).`;
    addText(savedSuitesHost, "p", "report-error", unavailableMessage);
    addText(timestampedRunsHost, "p", "empty-state", "Timestamped run data is unavailable.");
    setTestLabStatus(unavailableMessage, true);
  } finally {
    refreshTestLabButton.disabled = false;
    setRunButtonsDisabled(Boolean(activeEvaluationSuiteId || evaluationRunStarting));
  }
}

refreshTestLabButton.addEventListener("click", () => refreshTestLabReports());

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
    ["Classification time", formatLatency(payload.classification_latency_ms)],
    ["Answer time", formatLatency(payload.answer_generation_latency_ms)],
    ["Cloud time", formatLatency(payload.cloud_latency_ms)],
    ["Classification", payload.classification_location === "local" ? "Local" : payload.classification_location ?? "Unavailable"],
    ["Answer", answerProduction(payload)],
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

function answerProduction(payload) {
  if (payload.execution_status === "local_generation_failed") return "Generation failed";
  if (!payload.answer) return "Not generated";
  if (payload.request_sent_to_cloud === true) return "Generated by cloud";
  if (payload.final_route === "LOCAL") return "Generated locally";
  return "Generated";
}

function updateLiveRouting(payload, requestText, received = true, pending = false, failure = null) {
  const diagram = byId("routeDiagram");
  const outcome = byId("routingOutcome");
  const routeNodes = [...diagram.querySelectorAll("[data-route-node]")];
  for (const node of routeNodes) node.classList.remove("is-active");
  diagram.querySelector('[data-diagram-node="router"]').classList.remove("is-active");

  let state = "route";
  let title;
  let detail;
  let selectedRoute = null;
  const executionStatus = payload?.execution_status ?? "";
  if (pending) {
    state = "pending";
    title = "Waiting for backend result";
    detail = "No route is highlighted while the latest request is being processed.";
  } else if (!received) {
    state = "unavailable";
    const disconnected = failure?.status === 0;
    title = disconnected ? "Backend disconnected" : "Backend response unavailable";
    detail = disconnected
      ? "The backend could not be reached; no route is highlighted."
      : "No backend route was received, so no route is highlighted.";
  } else if (payload?.privacy_blocked === true || executionStatus === "blocked_by_privacy_shield") {
    state = "blocked";
    title = "Blocked by Privacy Shield";
    detail = "The backend blocked this request before sending it to the cloud.";
  } else if (payload?.final_route === "CLARIFICATION") {
    state = "clarification";
    title = "Request needs clarification";
    detail = payload.message || "The backend asked for clarification; no device action was run.";
  } else if (payload?.final_route === "COMMAND_UNSUPPORTED") {
    state = "unsupported";
    title = "Command not supported";
    detail = payload.message || "The backend did not recognize this as a supported command.";
  } else if (executionStatus === "device_control_not_performed") {
    state = "device-not-controlled";
    title = "No device was controlled";
    detail = payload.message || "The request did not match a supported device command; nothing was controlled.";
  } else if (payload?.final_route === "LOCAL" || payload?.final_route === "CLOUD" || payload?.final_route === "COMMAND") {
    selectedRoute = payload.final_route;
    title = `${selectedRoute} route selected`;
    detail = payload.message || `The backend returned the ${selectedRoute} route.`;
  } else {
    state = "unavailable";
    title = "No route selected";
    detail = payload?.message || "The backend did not return a routable final route.";
  }

  diagram.dataset.state = state;
  outcome.dataset.state = state;
  if (selectedRoute) {
    diagram.querySelector('[data-diagram-node="router"]').classList.add("is-active");
    diagram.querySelector(`[data-route-node="${selectedRoute}"]`)?.classList.add("is-active");
  }
  byId("routingSummary").textContent = title;
  byId("routingContext").textContent = received
    ? "Shown from the most recent /route response. Route highlighting follows final_route, not the classifier label."
    : pending
      ? "Waiting for the latest /route response; no route has been selected yet."
      : "A request was attempted, but the backend returned no route result.";
  byId("diagramRequest").textContent = requestText ? requestText.replace(/\s+/g, " ").slice(0, 88) : "No request yet";
  byId("outcomeSymbol").textContent = state === "blocked" ? "×" : state === "clarification" ? "?" : state === "unsupported" || state === "device-not-controlled" ? "!" : selectedRoute ? "✓" : "·";
  byId("outcomeTitle").textContent = title;
  byId("outcomeDetail").textContent = detail;
  byId("routingTimestamp").textContent = received ? new Date().toLocaleString() : pending ? "Waiting for backend result" : "No backend result received";
  const routeText = selectedRoute ? `The backend returned ${selectedRoute}. Only that route is highlighted.` : `${title}. No normal route is highlighted.`;
  diagram.setAttribute("aria-label", routeText);
  playgroundStatus.textContent = `Live Routing updated: ${title}.`;
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
  const routeLabel = payload.final_route ?? "ERROR";
  const routeBadge = addText(header, "span", `route-badge route-${String(routeLabel).toLowerCase()}`, routeLabel);
  routeBadge.setAttribute("aria-label", `Final route: ${routeLabel}`);
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
  const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
  card.scrollIntoView({ block: "nearest", behavior: reduceMotion ? "auto" : "smooth" });
  sessionItems += 1;
  playgroundStatus.textContent = isClarification ? "Request needs clarification. Edit it and resend." : title;
}

requestForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const requestText = requestInput.value.trim();
  if (!requestText || playgroundBusy) return;
  playgroundBusy = true;
  updateComposer();
  latestRouteResult = null;
  updateLiveRouting(null, requestText, false, true);
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
    latestRouteResult = { payload, requestText };
    updateLiveRouting(payload, requestText);
    renderResult(requestText, payload);
    void refreshOverview();
  } catch (error) {
    pending.remove();
    latestRouteResult = null;
    updateLiveRouting(null, requestText, false, false, error);
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
if (latestRouteResult) updateLiveRouting(latestRouteResult.payload, latestRouteResult.requestText);
refreshOverview();
refreshTestLabReports(false);
