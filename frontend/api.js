const JSON_HEADERS = { Accept: "application/json" };

export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function getJson(path, { signal } = {}) {
  let response;
  try {
    response = await fetch(path, {
      method: "GET",
      headers: JSON_HEADERS,
      cache: "no-store",
      credentials: "same-origin",
      signal,
    });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new ApiError("The backend could not be reached.");
  }

  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new ApiError("The backend returned an unreadable response.", response.status);
  }

  if (!response.ok) {
    throw new ApiError(`Backend request failed (${response.status}).`, response.status);
  }
  return payload;
}

export async function postJson(path, body, { signal } = {}) {
  let response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers: { ...JSON_HEADERS, "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
      credentials: "same-origin",
      signal,
    });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new ApiError("The backend could not be reached.");
  }

  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new ApiError("The backend returned an unreadable response.", response.status);
  }
  if (!response.ok) {
    throw new ApiError(`Backend request failed (${response.status}).`, response.status);
  }
  return payload;
}

export function routeRequest(requestText, options) {
  return postJson("/route", { request_text: requestText }, options);
}

export function loadEvaluationReports(options) {
  return getJson("/evaluation-reports", options);
}

export function startEvaluationRun(suiteId, options) {
  return postJson("/evaluation-runs", { suite_id: suiteId }, options);
}

export function getEvaluationRun(runId, options) {
  return getJson(`/evaluation-runs/${encodeURIComponent(runId)}`, options);
}

export async function loadOverview(signal) {
  const [health, stats, devices, history, activity] = await Promise.allSettled([
    getJson("/health", { signal }),
    getJson("/stats", { signal }),
    getJson("/devices", { signal }),
    getJson("/history?limit=20", { signal }),
    getJson("/activity?days=30", { signal }),
  ]);
  return { health, stats, devices, history, activity };
}
