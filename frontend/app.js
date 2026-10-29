import { loadOverview, routeRequest } from "./api.js";

const byId = (id) => document.getElementById(id);
const refreshButton = byId("refreshStatus");
const toast = byId("toast");
let activeController = null;
let playgroundBusy = false;
let sessionItems = 0;
let latestRouteResult = null;
const SVG_NS = "http://www.w3.org/2000/svg";

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
  const colors = { LOCAL: "#62d6c5", CLOUD: "#a99aff", COMMAND: "#f3bd73", COMMAND_UNSUPPORTED: "#ef7b88", CLARIFICATION: "#9eacc0", ERROR: "#bd7883" };
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
    svg.append(svgElement("rect", { x: 174, y, width: Math.max(2, 400 * count / maxValue), height: 18, rx: 5, fill: colors[route] ?? "#8b9ab0", class: "chart-bar" }));
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
    if (!applyUnavailable(result.history, renderHistory, "Request history is unavailable.")) {
      const body = byId("historyRows");
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.className = "table-empty";
      cell.colSpan = 7;
      cell.textContent = "Request history is unavailable.";
      row.append(cell);
      body.replaceChildren(row);
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
  const labels = { overview: "OVERVIEW", playground: "AI PLAYGROUND", "live-routing": "LIVE ROUTING", analytics: "ANALYTICS" };
  const titles = { overview: "Overview", playground: "AI Playground", "live-routing": "Live Routing", analytics: "Analytics" };
  document.querySelector(".breadcrumbs strong").textContent = labels[selectedView];
  document.title = `Smart AI Router · ${titles[selectedView]}`;
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

function updateLiveRouting(payload, requestText, received = true, pending = false) {
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
    title = "Backend response unavailable";
    detail = "No backend route was received, so no route is highlighted.";
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
    updateLiveRouting(null, requestText, false);
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
