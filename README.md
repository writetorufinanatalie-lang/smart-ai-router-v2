# Smart AI Router

Smart AI Router is a local-first request-routing dashboard. A local Ollama model classifies a request as `SIMPLE`, `COMPLEX`, or `COMMAND`. The router then uses a local answer generator, a cloud adapter, or a strict command whitelist. Commands update simulated in-memory devices only; they do not control real hardware.

The browser dashboard is served by FastAPI from `frontend/`. The backend records request metrics in SQLite without storing request text, answers, or API keys. Evaluation jobs run the real local classifier and router and save timestamped reports.

## Request flow and safety boundaries

See [the architecture diagram](docs/architecture.md).

- **Classification is local.** `backend/classifier.py` connects to Ollama at `127.0.0.1:11434`, using `qwen2.5:1.5b` by default.
- **Commands require a parser match.** The rule-based whitelist must understand the complete command before the simulated device state can change. A model label alone never executes an action.
- **Unclear or unsupported requests do not execute.** The router returns a clarification or unsupported status as appropriate.
- **Cloud requests are not answered unless a provider sender is configured.** No cloud provider sender is included, so the normal cloud adapter returns `Cloud route selected, but the request could not be processed`; it does not invent an answer.
- **The Privacy Shield checks before a cloud handoff.** It looks for email, phone-number, and card-like patterns. It can miss formats and is not a complete detector.
- **Device state is simulated, in-memory, and resets on server restart.**

## Setup on Windows

Run these commands in **PowerShell**, from the project folder. The current project environment was tested with Python 3.14.3; other Python versions have not been verified here.

1. Install 64-bit Python 3.14 and Ollama for Windows. Start Ollama if the installer did not start its local service.
2. Open PowerShell in the project folder and create the virtual environment:

   ```powershell
   py -3.14 -m venv .venv
   ```

   This creates an isolated Python environment in `.venv`.

3. Activate it:

   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

   If PowerShell blocks activation, allow scripts for this PowerShell process only, then retry activation:

   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   .\.venv\Scripts\Activate.ps1
   ```

4. Install the pinned project dependencies:

   ```powershell
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```

5. Download the local model and confirm Ollama lists it:

   ```powershell
   ollama pull qwen2.5:1.5b
   ollama list
   ```

   You can also check that it responds locally:

   ```powershell
   ollama run qwen2.5:1.5b "What is 2 + 2?"
   ```

6. Start the dashboard and API from the project root:

   ```powershell
   python -m uvicorn backend.main:app --reload
   ```

   Open <http://127.0.0.1:8000/>. Keep the terminal running while using the dashboard. The `/health` endpoint reports the actual backend, Ollama/model, and cloud-configuration status.

## Optional cloud environment setting

`.env.example` contains the optional `CLOUD_API_KEY` setting. To make a local environment file:

```powershell
Copy-Item .env.example .env
```

`.env` is ignored by Git. **There is no cloud provider or provider sender configured in this project.** Setting `CLOUD_API_KEY` alone will not enable cloud processing or produce a cloud answer. Do not add a real key expecting the cloud route to work until a provider sender is deliberately implemented and tested.

## Try the routes

Open **AI Playground** in the dashboard and submit these example requests. Model labels can vary; the examples are not guaranteed classification results.

| Example request | Expected behavior to inspect |
| --- | --- |
| `What is 2 + 2?` | A short `SIMPLE` request is classified locally and answered by the local model if it is available. |
| `Compare solar and wind power for a small town, including cost, reliability, and maintenance.` | A `COMPLEX` label selects the cloud route. With no provider configured, the honest unavailable message is shown. |
| `Turn on the desk light.` | The whitelist parser recognizes a supported command and updates the simulated device state. |
| `Set the desk light brightness to 40 percent.` | The whitelist parser accepts the supported brightness value and updates simulated state. |

The command examples only affect the in-memory simulation. Never interpret the dashboard response as control of a physical device.

## API endpoints

The interactive API schema is available at <http://127.0.0.1:8000/docs> while the server is running.

| Method and path | Purpose |
| --- | --- |
| `GET /` | Serve the dashboard from `frontend/`. |
| `POST /route` | Classify and route a user request; request text is not written to metrics. |
| `GET /stats` | Return aggregates computed from SQLite request and evaluation rows. |
| `GET /history?limit=20` | Return recent normal-request metadata without request text. `limit` is 1–200. |
| `GET /activity?days=30` | Return daily normal-request counts. `days` is 1–365. |
| `GET /devices` | Return simulated in-memory device state and its reset-on-restart status. |
| `GET /health` | Report backend/metrics-store, Ollama/model, and cloud configuration status. |
| `POST /evaluate` | Evaluate a submitted batch against expected labels and optional expected routes. |
| `GET /evaluation-results` | Return the latest saved evaluation result, if available. |
| `GET /evaluation-reports` | Return the original, held-out, and generalization reports separately, plus timestamped runs. |
| `POST /evaluation-runs` | Start one background run. Send `{"suite_id":"original_38"}`, `{"suite_id":"held_out_15"}`, or `{"suite_id":"generalization_18"}`. |
| `GET /evaluation-runs/{run_id}` | Poll a background run for progress or its completed result. |

## Tests and evaluations

Run the automated test suite from the project root with the virtual environment active:

```powershell
python -m pytest
```

The classifier test that guards against external classification requests is:

```powershell
python -m pytest tests/test_classifier.py::test_default_classification_uses_loopback_and_makes_no_external_network_call
```

To run each fixed evaluation set with the real local model/router, first confirm Ollama is running and the model is available. These PowerShell commands write each run to a new timestamped file under `data/evaluation_runs/`, leaving the three saved baseline reports untouched:

```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
python -m scripts.run_evaluation --cases tests/evaluation_cases.json --output "data/evaluation_runs/original_38-$stamp.json"

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
python -m scripts.run_evaluation --cases tests/held_out_evaluation_cases.json --output "data/evaluation_runs/held_out_15-$stamp.json"

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
python -m scripts.run_evaluation --cases tests/generalization_evaluation_cases.json --output "data/evaluation_runs/generalization_18-$stamp.json"
```

Each run sends each case through the local classifier and router, reports actual results, and records evaluation metrics separately from normal user requests. These commands can take a few minutes on a CPU-only computer. They require Ollama and the model; they are not mock evaluations.

### Verifying classification stays local

Use all three checks for complementary evidence:

1. **Inspect the code:** `backend/classifier.py` sets the Ollama host to `http://127.0.0.1:11434`; the classifier call uses that local client.
2. **Run the mock network test above:** it intercepts the HTTP client request, verifies the host is loopback, and fails if classification attempts a non-local host. This tests the code path without contacting a service.
3. **Try a real request with Wi-Fi off:** first download the model and start Ollama and the backend while connected. Then turn off Wi-Fi and submit a `SIMPLE` request. The local classifier and local answer model should already be available on the machine. Check the response metadata for local classification. This is a practical check of that run, not a general network audit of the whole computer.

Classification and local answer generation use Ollama on the same computer. The cloud adapter does not call an external service in the current configuration.

## Results and limitations

The saved reports record these classifier-correct and final-route-correct counts:

| Evaluation set | Classification | Final route |
| --- | ---: | ---: |
| Original, 38 hand-written cases | 31/38 | 36/38 |
| Held-out, 15 hand-written cases | 12/15 | 7/15 |
| Generalization, 18 hand-written cases | 10/18 | 12/18 |

These are small, hand-written snapshots, not estimates of general performance. The parser was developed around the first set, so its original-set result is not an unbiased measure of generalization. The Privacy Shield is pattern-based and can miss sensitive formats. No cloud provider is configured, so cloud-selected requests cannot get provider answers. Device state is simulated and resets when the server restarts. Latency was measured on one CPU-only laptop; it is not a hardware-independent benchmark. Results can vary with model version, Ollama, machine load, and prompt phrasing.

## Troubleshooting

- **`/health` reports Ollama unavailable:** ensure the Ollama application/service is running. If it is not already running, start `ollama serve` in another terminal. Then run `ollama list` and check for `qwen2.5:1.5b`.
- **The model is missing:** run `ollama pull qwen2.5:1.5b` and retry after it finishes.
- **The local answer fails:** check the Ollama service and model, then inspect the backend terminal for the reported local-generation failure. Classification and answer generation are separate steps.
- **A complex request says it could not be processed:** this is expected until a cloud provider sender is configured. A key by itself is insufficient, and the app does not fabricate an answer.
- **PowerShell cannot activate `.venv`:** use the process-scoped execution-policy command in the setup section. It does not change the machine-wide policy.
- **Port 8000 is already in use:** start Uvicorn on another available port, for example `python -m uvicorn backend.main:app --reload --port 8001`, then open `http://127.0.0.1:8001/`.

## Future improvements

- Add more independently authored and held-out examples before changing the classifier or command parser, then report each set separately.
- Profile classification and answer generation across multiple hardware configurations before making performance claims.
- If cloud answers are needed, choose a provider and add an explicit sender, configuration checks, and tests for the Privacy Shield and honest failure behavior before enabling it.
- Add real device integrations only with explicit authentication, authorization, and safety checks; the current simulated whitelist is not a hardware integration.

### Raspberry Pi exploration (optional, untested)

This project has not been tested on a Raspberry Pi. Before trying one, check that the target Pi OS, Python build, Ollama runtime, and `qwen2.5:1.5b` are supported on that exact hardware. Install and run the local model, then run pytest and the evaluation sets on the device. Measure latency and memory there before deciding whether it is suitable for a demo; laptop results do not predict Pi performance.
