# PROJECT: SMART AI ROUTER WITH INTELLIGENT ROUTING DASHBOARD

Act as a senior AI engineer, software architect, and technical mentor. Help me plan and eventually build a complete, working AI routing system for a startup task.

I want to build a technically impressive project that goes beyond the basic requirements while remaining practical to implement and demonstrate on a normal laptop.

IMPORTANT: We are starting from the beginning. Do not assume that any component has already been implemented.

For now, I want you to analyse the requirements, recommend the architecture, and create a development plan. Do not generate the complete codebase yet.

---

# 1. ORIGINAL STARTUP TASK

The startup gave me the following assignment:

"Build a small AI system that decides whether a user's request can be handled by a Small Language Model (SLM) or should be sent to a larger cloud LLM.

Examples:

Input: What is 2 + 2?
→ SLM → Answer locally.

Input: Tell me a 500-word story about a dragon.
→ SLM → Classify as complex → Send to cloud LLM.

Input: Turn on the light.
→ SLM → Classify as a command → Execute a local function.

Requirements:
1. Pick an SLM.
2. Build the classifier/router.
3. Create at least 20 test queries.
4. Run it locally on a normal laptop.
5. The classification step must not call an external LLM API.
6. If possible, test it on a Raspberry Pi or another edge device.
7. Build a tiny demo UI.
8. Additional interesting features are encouraged."

The goal is to satisfy every mandatory requirement and add meaningful features that demonstrate good engineering.

# 2. PROJECT CONCEPT

I want to build a Smart AI Router with an interactive dashboard.

The application will accept user requests, classify them using a locally running SLM, select an appropriate route, perform the corresponding action, and display the result.

There are three core routes.

## Route A: SIMPLE

Example:
"What is 2 + 2?"

Expected workflow:
1. Receive the user's request.
2. Classify it using the local SLM.
3. Select the local route.
4. Generate the answer using the local SLM or suitable local logic.
5. Display the answer and routing information.

## Route B: COMPLEX

Example:
"Write a 500-word story about a dragon."

Expected workflow:
1. Classify the request using the local SLM.
2. Select the cloud route.
3. Send the request to a configured cloud LLM API.
4. Generate and display the answer.

If cloud API access is unavailable, clearly report that the request was routed to the cloud but could not be processed. Do not pretend that a cloud answer was generated.

## Route C: COMMAND

Example:
"Turn on the light."

Expected workflow:
1. Classify the request using the local SLM.
2. Select the command route.
3. Validate the requested action.
4. Execute a predefined, safe local function.
5. Display the execution result.

Commands can be simulated in software. No physical hardware is required for the initial prototype.

The system must distinguish classification, routing, answer generation, and command execution.

---

# 3. NON-NEGOTIABLE TECHNICAL REQUIREMENT

The classification step must run locally without calling an external LLM API.

Please explain how to enforce and verify this requirement.

The architecture should ensure:
- The SLM runs locally.
- Classification is performed locally.
- The router makes decisions based on the classifier output and validated rules.
- Cloud requests occur only after the local classifier selects the cloud route.
- Local commands are restricted to predefined functions.
- Arbitrary model-generated text cannot execute unrestricted operating-system commands.
- Cloud API keys are stored securely.
- Classification remains available without internet access, assuming the local model and runtime are installed.

Distinguish clearly between the local SLM, the routing engine, the cloud LLM, and the local command functions.

Do not claim that classification is completely independent of external services unless the implementation and tests support that claim.

---

# 4. TECHNOLOGY STACK

Evaluate and recommend a suitable stack.

Potential technologies:

- Local SLM: Qwen2.5-1.5B-Instruct or another suitable lightweight instruction-tuned model.
- Model runtime: Ollama.
- Backend: Python and FastAPI.
- Frontend: HTML, CSS, and JavaScript.
- Testing: pytest.
- Cloud LLM: A provider API selected later.
- Version control: Git.

Do not automatically assume these are the best options.

Compare relevant alternatives and recommend the best practical stack based on:
- Laptop compatibility.
- RAM and memory usage.
- Model quality.
- Inference speed.
- Installation difficulty.
- Reliability.
- Ease of development.
- Demo quality.

Explain the hardware requirements and limitations of the recommended SLM.

Do not assume my laptop specifications are known. Identify the hardware information needed before finalizing the model.

---

# 5. THREE IMPORTANT ADDITIONAL FEATURES

I want to add meaningful functionality beyond the minimum requirements.

Recommend how to implement the following three features.

## Feature 1: Intelligent Routing Analytics

The application should measure and display actual system performance.

Potential metrics:
- Total requests processed.
- Number of SIMPLE requests.
- Number of COMPLEX requests.
- Number of COMMAND requests.
- Number of requests processed locally.
- Number of requests routed to the cloud.
- Average classification latency.
- Local response-generation latency.
- Cloud response latency.
- Classification accuracy from the test suite.

Requirements:
- Explain what data the backend must collect.
- Recommend an appropriate way to store request metrics.
- Explain how to calculate the statistics.
- Distinguish classification time from answer-generation time.
- Ensure that the dashboard uses actual backend data rather than hardcoded values.
- Do not invent performance results.

Consider whether in-memory storage is sufficient for an initial demo or whether SQLite is more appropriate.

## Feature 2: Intelligent Fallback and Uncertainty Handling

The classifier may produce an invalid result, misclassify a request, or encounter an ambiguous input.

Examples:
- "Explain AI briefly but include every technical detail."
- "Can you turn on my bedroom light?" when only a simulated desk light exists.
- A request that does not clearly fit any of the three categories.

The system should:
- Validate classification outputs.
- Handle malformed model responses.
- Apply a predefined fallback policy.
- Ask for clarification when necessary.
- Handle model failures and timeouts.
- Avoid unsafe command execution.
- Handle cloud API failures gracefully.

Do not rely solely on a model's self-reported confidence score.

Explain how to evaluate the fallback policy using test cases and measurable criteria.

## Feature 3: Privacy-Aware Routing

The interface should make it clear whether a request is handled locally or sent to a cloud provider.

Examples:

Local processing:
- Route: LOCAL SLM.
- Processing location: Local machine.
- External LLM API used for classification: No.

Cloud processing:
- Route: CLOUD LLM.
- Processing location: External provider.
- User request sent to the configured provider: Yes.

Requirements:
- Show privacy information based on actual execution metadata.
- Clearly distinguish local classification from cloud answer generation.
- Do not make unsupported privacy or security guarantees.
- Explain what information leaves the machine when cloud processing is enabled.

Recommend how the backend should expose this information to the frontend.

---

# 6. ADDITIONAL IDEAS

In addition to the three features above, consider whether any of the following would provide substantial value:

- A live routing-flow visualization.
- A local-versus-cloud latency comparison.
- Cloud API cost estimates.
- A testing playground.
- A classification accuracy dashboard.
- Model availability indicators.
- Offline support for local requests.
- A comparison between predicted and actual routes.
- A route explanation showing why a category was selected.

Recommend only the features that add genuine value.

Prioritize a reliable core system over an excessive number of features.

If cost estimation is suggested, distinguish measured API charges from estimates based on token usage and provider pricing.

If confidence-based routing is suggested, explain how the confidence mechanism would be validated or calibrated.

---

# 7. DEMO UI

I want a clean, professional, interactive web interface.

The interface should contain four main sections.

## A. AI Playground
- Text input.
- Send button.
- Model-generated answer or command result.
- Predicted category.
- Selected route.
- Processing status.
- Classification latency.

## B. Routing Visualization
- Display the actual route selected by the backend.
- Show the local classification stage.
- Show the local SLM, cloud LLM, or local function used for the request.
- Reflect actual execution rather than a predefined animation.

## C. Analytics Dashboard
- Total request count.
- Route distribution.
- Average classification latency.
- Response-generation latency.
- Actual test accuracy when test results are available.

## D. Privacy and System Status
- Local versus cloud execution.
- Local model availability.
- Cloud service availability when configured.
- Whether the request was actually sent to an external provider.

Explain which frontend components need backend APIs and how the data should flow.

Do not generate frontend code yet.

---

# 8. BACKEND ARCHITECTURE

Recommend a clear architecture that separates responsibilities.

Possible components:

1. API layer.
2. Local SLM inference service.
3. Classification and validation layer.
4. Routing engine.
5. Local answer-generation service.
6. Cloud LLM adapter.
7. Safe command registry.
8. Request metrics and analytics service.
9. Fallback and error-handling service.
10. Frontend integration layer.

You may simplify or reorganize these components if a smaller architecture is more appropriate.

Explain:
- The purpose of each component.
- The data exchanged between components.
- Suggested API endpoints.
- Request and response formats.
- Error-handling behavior.
- How the frontend will communicate with the backend.

Avoid unnecessary microservices or complex infrastructure.

---

# 9. TESTING AND EVALUATION

The system must include at least 20 test queries across all three categories.

The test dataset should include:
- Straightforward requests.
- Complex generation requests.
- Valid commands.
- Ambiguous requests.
- Invalid classification responses.
- Local model failures.
- Cloud API failures.
- Unsupported commands.

For each query, record:
- Input.
- Expected category.
- Predicted category.
- Selected route.
- Correctness.
- Classification latency.
- Any relevant execution result.

Recommend how to measure:
- Overall classification accuracy.
- Per-category precision and recall.
- Confusion matrix.
- Classification latency.
- Local generation latency.
- Cloud response latency.
- Routing correctness.
- Fallback behavior.

Explain the limitations of evaluating the system using only 20 queries.

Do not invent test results. Provide a reproducible testing methodology.

Also explain how to verify that no external LLM API is called during classification, using code inspection, mock tests, and suitable runtime checks.

---

# 10. DEVELOPMENT ROADMAP

Create a phased plan.

Suggested phases:

Phase 1: Understand the requirements and inspect the development environment.

Phase 2: Choose the SLM and verify local execution.

Phase 3: Implement local classification.

Phase 4: Implement and validate the routing engine.

Phase 5: Implement local answer generation and safe command execution.

Phase 6: Add cloud LLM integration when API access is available.

Phase 7: Implement analytics, fallback handling, and privacy metadata.

Phase 8: Build the frontend and connect it to the backend.

Phase 9: Create at least 20 test queries and evaluate performance.

Phase 10: Run the application locally and prepare documentation.

Phase 11: Consider edge-device testing if practical.

For each phase, specify:
- Objectives.
- Files or components involved.
- Dependencies.
- Expected result.
- Tests required before proceeding.
- Potential difficulties.

Adjust the order if there is a better engineering approach.

---

# 11. REQUIRED DELIVERABLES

The final project should contain:

1. A working local SLM setup.
2. A local request classifier.
3. A routing engine.
4. Three functioning routes.
5. Optional real cloud LLM integration.
6. A safe local command system.
7. An interactive demo UI.
8. Routing analytics.
9. Fallback and uncertainty handling.
10. Privacy-aware execution metadata.
11. At least 20 test queries.
12. Actual test results and performance measurements.
13. A system architecture diagram.
14. A README with setup and execution instructions.
15. A limitations and future-improvements section.
16. Optional Raspberry Pi or edge-device testing.

---

# 12. HOW I WANT YOU TO RESPOND

Act as a senior AI engineer helping me make good technical decisions.

I am starting this project from the beginning and want to understand what I build.

For now, provide planning and analysis only.

Respond in this order:

1. Explain the project in simple language.
2. Explain the differences between an SLM, classifier, router, cloud LLM, and local function.
3. Recommend the overall architecture.
4. Recommend a suitable model and explain its hardware requirements.
5. Recommend the technology stack.
6. Explain the three request-processing workflows.
7. Explain how to implement the three additional features.
8. Recommend any other genuinely valuable enhancements.
9. Describe the backend APIs and frontend components.
10. Propose a phased development roadmap.
11. Identify technical risks and how to mitigate them.
12. Describe the final demonstration and deliverables.

Do not generate the entire codebase yet.

Do not assume that cloud API credentials are available.

Do not assume any existing implementation is available.

Do not invent benchmark results or claim unimplemented features are working.

Explain trade-offs honestly and prioritize practical, testable engineering.

After providing the plan, wait for my response before proceeding to implementation.