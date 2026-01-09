# Project Summary — Journey (CPU API + RunPod GPU Serverless)

## Objectives

- Provide an **always-on HTTP API** (`cpu_api`) that client apps can call with a user message.
- Use a **RunPod Serverless GPU endpoint** (`gpu_serverless`, in a separate repo) to run LLM inference.
- Maintain lightweight **per-user state** (signals + history snapshots) and compute a simple **stage probability** output from that state.
- Persist **conversation history + per-turn sentiment signals** to Supabase for timeline graphs and future curve prediction.

## High-level architecture

- **CPU API (FastAPI)**:
  - Exposes:
    - `GET /health` → `{ "ok": true }`
    - `POST /chat` → returns `assistant_message` + assessment metadata
  - Builds a system prompt from a config (question bank + rules) and sends chat `messages` to the GPU endpoint.
  - Parses model output (expects a single JSON object) and extracts:
    - `assistant_message`
    - `signals` (Q1..Q20, values in the configured scale)
  - Normalizes signals, updates per-user state, and computes:
    - `stage_probs`, `confidence`, `coverage`

- **GPU Serverless (vLLM)** *(separate repo / separately deployed)*:
  - RunPod handler receives `messages`, runs vLLM inference, returns `raw_text` with the model output.

## What we established so far

- **CPU API → GPU Serverless connectivity** works end-to-end using RunPod `runsync`.
- **Health checks**:
  - Both services respond to `/health`.
- **State storage robustness**:
  - CPU API supports Redis-backed state (via `REDIS_URL`) and now tolerates Redis runtime connection failures without crashing (falls back to “no stored state” behavior during outages).
- **Supabase persistence (conversations + signals timeline)**:
  - CPU API can optionally write each user/assistant turn to a Supabase table.
  - CPU API can optionally write per-turn signal snapshots (signals + stage_probs + confidence + coverage + config metadata).
  - If client doesn’t provide `history`, CPU API can load recent history from Supabase to keep chats coherent across restarts.
- **CI/CD for CPU API**:
  - GitHub Actions workflow builds & pushes a Docker image to GHCR on pushes (CPU API repo only).
  - The RunPod CPU Pod can pull the published image and auto-start uvicorn via `Dockerfile` `CMD`.

## Repos (important separation)

- **CPU API repo**: [`EsforgeUE5/journey_api`](https://github.com/EsforgeUE5/journey_api)
- **GPU Serverless repo**: separate repository, linked/deployed to the RunPod Serverless Endpoint independently.

## Known issues / next follow-ups

- **GPU worker occasionally exits with code 1**: intermittent worker failures still need investigation (likely GPU worker runtime/config/memory/disk related). We deferred this intentionally after confirming the full request path works.


