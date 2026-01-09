# RunPod Setup Guide — `cpu_api` (Journey API)

This guide configures the **CPU API** container to run on a RunPod CPU Pod as an always-on backend:

- **Source repo**: [`EsforgeUE5/journey_api`](https://github.com/EsforgeUE5/journey_api)
- **Container starts**: `uvicorn app.main:app --host 0.0.0.0 --port 8000` (already in `Dockerfile`)

## Container image: where it gets published

GitHub Actions builds & pushes the Docker image to **GitHub Container Registry (GHCR)**.

- **Registry**: `ghcr.io`
- **Image name**: `ghcr.io/EsforgeUE5/journey_api`
- **Tags you’ll use most**:
  - **Latest**: `ghcr.io/EsforgeUE5/journey_api:cpu_api-latest`
  - **Immutable** (per-commit): `ghcr.io/EsforgeUE5/journey_api:cpu_api-<git-sha>`

If the image/package is private, RunPod must be able to pull from GHCR with credentials. If it’s public, it will pull without auth.

## CI/CD prerequisites (GitHub → GHCR)

1. Ensure this workflow exists in the repo at:
   - `.github/workflows/cpu_api_ghcr.yml`
2. Push to `main` or `master`.
3. In GitHub, confirm the workflow runs successfully (repo → **Actions**).
4. Confirm a package appears (repo/org → **Packages**) named `journey_api`.

## RunPod CPU Pod configuration

### Image

Set the pod’s container image to:

- `ghcr.io/EsforgeUE5/journey_api:cpu_api-latest`

### Exposed port

- **Container port**: `8000`

### Environment variables (CPU API)

These are read by `cpu_api/app/runpod_client.py` and `cpu_api/app/state_store.py`.

#### Required (for CPU → RunPod Serverless GPU calls)

- **`RUNPOD_API_KEY`**: your RunPod API key (used to call the RunPod API).
- **`RUNPOD_ENDPOINT_ID`**: the **Serverless Endpoint ID** for your GPU endpoint (the v2 endpoint id).

#### Optional (controls inference call behavior)

- **`RUNPOD_SYNC`**: defaults to `"true"` (currently `runsync` is used; leaving default is fine).
- **`RUNPOD_TIMEOUT_SECONDS`**: default `"60"`; increase if GPU generations time out.

#### Optional (state persistence)

- **`REDIS_URL`**:
  - If **unset/empty**: state is stored **in-memory** (resets when the pod restarts).
  - If set: should be a reachable Redis URL (example: `redis://<host>:6379/0`).
  - Note: if Redis becomes unreachable at runtime, the API will **fall back to behaving like an empty store** (no crash, but no persistence during outage).
- **`STATE_TTL_SECONDS`**: default `"86400"` (used only when Redis is enabled, for key expiry).

#### Optional (Supabase persistence for conversations + signals timeline)

If configured, the CPU API will:
- **Read** recent conversation history from Supabase when `history` is not provided in the request.
- **Write** each user+assistant turn to a conversations table.
- **Write** a per-turn **signals snapshot** to a snapshots table (ideal for timeline graphs + future prediction).

Environment variables:

- **`SUPABASE_URL`**: your Supabase project URL (e.g. `https://<ref>.supabase.co`)
- **`SUPABASE_SERVICE_ROLE_KEY`** *(recommended)*: server-side key that bypasses RLS
  - Alternatively supported: **`SUPABASE_KEY`**
- **`SUPABASE_TIMEOUT_SECONDS`**: default `"10"`
- **`SUPABASE_CONVERSATIONS_TABLE`**: default `journey_conversations`
- **`SUPABASE_SIGNAL_SNAPSHOTS_TABLE`**: default `journey_signal_snapshots`

## Supabase SQL (create tables)

Run this in Supabase (SQL editor). It creates two tables optimized for “timeline graphs”:

```sql
-- UUID helper (needed for gen_random_uuid())
create extension if not exists pgcrypto;

-- Conversations: one row per message (user/assistant)
create table if not exists public.journey_conversations (
  id uuid primary key default gen_random_uuid(),
  user_id text not null,
  role text not null check (role in ('user','assistant')),
  content text not null,
  model_id text null,
  request_id text null,
  created_at timestamptz not null default now()
);

create index if not exists journey_conversations_user_time
  on public.journey_conversations (user_id, created_at desc);

-- Signals snapshots: one row per turn with full signal map + assessment outputs
create table if not exists public.journey_signal_snapshots (
  id uuid primary key default gen_random_uuid(),
  user_id text not null,
  signals jsonb not null,
  stage_probs jsonb not null,
  confidence text not null,
  coverage double precision not null,
  config_version text not null,
  config_hash text not null,
  model_id text null,
  request_id text null,
  created_at timestamptz not null default now()
);

create index if not exists journey_signal_snapshots_user_time
  on public.journey_signal_snapshots (user_id, created_at desc);
```

Notes:
- If you enable **Row Level Security (RLS)**, you must add policies. For simplest server-side usage, set `SUPABASE_SERVICE_ROLE_KEY` in the CPU API and keep RLS policies strict (service role bypasses RLS).

## Serverless GPU Endpoint expectations (what CPU API sends)

The CPU API sends this payload to your GPU serverless endpoint:

- `messages`: list of `{ role: "system|user|assistant", content: "..." }`
- `max_tokens`: int
- `temperature`: float

Your GPU endpoint should return output containing `raw_text` (or compatible fields), e.g.:
- `{ "raw_text": "<model output>" }`

## Smoke tests (after pod is running)

### Health

- `GET /health` should return:
  - `{ "ok": true }`

### Chat

Send:

```json
{
  "user_id": "u1",
  "message": "I feel lonely and unsure I belong here."
}
```

Expected:
- HTTP 200
- A JSON body with:
  - `assistant_message` (string)
  - `stage_probs` (object)
  - `confidence` (string)
  - `coverage` (number)
  - `signals` (object)
  - `config_version` (string)

## Troubleshooting

### 500 errors mentioning Redis connection refused

- Unset `REDIS_URL`, or set it to a reachable Redis instance.
- If `REDIS_URL` is `redis://localhost:6379` but Redis isn’t running in the same pod/network, you’ll get connection failures.

### 502 “RunPod error” / “Inference call failed”

- Verify `RUNPOD_API_KEY` and `RUNPOD_ENDPOINT_ID` are correct.
- Verify the GPU Serverless Endpoint is deployed and responding.
- Increase `RUNPOD_TIMEOUT_SECONDS` if generations take longer.


