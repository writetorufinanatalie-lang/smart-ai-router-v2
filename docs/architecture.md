# Smart AI Router architecture

```mermaid
flowchart LR
    Browser[Browser dashboard<br/>frontend/]
    API[FastAPI<br/>/route and dashboard APIs]
    Router[SmartRouter<br/>route selection and safety]
    Classifier[Local classifier]
    Ollama[Ollama<br/>qwen2.5:1.5b]
    Answer[Local answer generator]
    Parser[Rule-based command whitelist]
    Devices[Simulated device registry<br/>in-memory; resets on restart]
    Cloud[Cloud adapter]
    Shield[Privacy Shield<br/>email, phone, card-like patterns]
    Provider[Provider sender<br/>not configured]
    SQLite[(SQLite metrics store)]
    Jobs[Background evaluation job<br/>one active run at a time]
    EvalScript[Evaluation script<br/>real local classifier and router]
    Reports[(Timestamped JSON reports)]

    Browser -->|HTTP| API
    API -->|user request| Router
    Router -->|classify| Classifier
    Classifier -->|loopback only| Ollama
    Ollama -->|label and reason| Classifier
    Classifier -->|classification result| Router

    Router -->|SIMPLE| Answer
    Answer -->|local generation| Ollama
    Router -->|COMMAND candidate| Parser
    Parser -->|complete whitelisted command only| Devices
    Devices -->|simulated result| Router
    Router -->|COMPLEX| Cloud
    Cloud --> Shield
    Shield -->|blocked patterns: no handoff| Cloud
    Shield -->|clear: would be eligible for handoff| Provider
    Provider -.->|no sender configured; honest unavailable response| Cloud
    Cloud --> Router
    Router -->|response metadata and stage timings| API

    API -->|normal request metrics| SQLite
    Jobs -->|runs selected evaluation suite| EvalScript
    EvalScript -->|real requests| Router
    EvalScript -->|evaluation rows, separate from user rows| SQLite
    EvalScript -->|progress and final report| Reports
    API -->|health, metrics, report and job endpoints| Browser
```

## Notes

- The classifier is configured for the loopback Ollama service and does not use an external LLM API for classification.
- The router uses the model label together with the rule-based parser. A command is not executed solely because the classifier returned `COMMAND`.
- The Privacy Shield is a local pattern check on the cloud path. It can miss sensitive formats.
- The cloud adapter has no configured provider sender in this project. A cloud-selected request therefore returns an unavailable result rather than a fabricated answer.
- Command outcomes update simulated in-memory state only. They do not control physical devices, and the state resets on server restart.
- SQLite stores metrics and evaluation aggregates without request text. Evaluation reports are written as JSON under `data/` (timestamped job runs are kept separately under `data/evaluation_runs/`).
