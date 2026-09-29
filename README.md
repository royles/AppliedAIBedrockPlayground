# Cloudera Blueprint: Bedrock Playground

A lightweight playground for experimenting with AWS Bedrock models on Cloudera AI (and locally). The React frontend provides a simple chat UI; the FastAPI backend handles all AWS connectivity and keeps credentials secure.

## Table of Contents

- [Overview](#overview)
- [Demo](#demo)
- [Use Case](#use-case)
- [Key Features](#key-features)
- [Quickstart](#quickstart)
- [Architecture / Software Components](#architecture--software-components)
- [Target Audience](#target-audience)
- [Repository Structure](#repository-structure)
- [Prerequisites](#prerequisites)
- [Hardware Requirements](#hardware-requirements)
- [Security](#security)
- [Switching Bedrock ↔ Local LLM](#switching-bedrock--local-llm)
- [API Endpoints](#api-endpoints)
- [Configuration](#configuration)
- [Supported Models](#supported-models)
- [Documentation](#documentation)

## Overview

Bedrock Playground is a reference blueprint for teams who want a secure, chat-style interface to Amazon Bedrock from Cloudera Machine Learning / Cloudera AI. Credentials and API keys stay on the Python backend; the browser only talks to `/api` on the same origin (or via Vite proxy in local dev). The same codebase runs as a two-process local stack (Vite + FastAPI) or as a single FastAPI process on CAI that serves the pre-built UI from `frontend/dist`.

## Demo

After deployment, open the application URL for the chat UI. For a quick API check without the UI:

- **Health**: `{app-url}/api/health`
- **Swagger**: `{app-url}/docs`

Record a Reprise or screen capture walkthrough and link it here when available.

## Use Case

Organizations using Cloudera AI need a fast way to validate Bedrock model access, compare models, and demo generative AI without embedding AWS SDK calls in notebooks or exposing keys in front-end code. This blueprint provides a minimal full-stack pattern: IAM or env-based credentials on the server, CORS-safe API design, and optional switch to a local OpenAI-compatible endpoint for offline or cost-controlled testing.

## Key Features

- Chat UI over Amazon Bedrock (Anthropic Claude, Amazon Nova, Meta Llama, Mistral, Titan, and more)
- FastAPI backend with boto3; no AWS secrets in the React app or in `GET /api/config`
- One-command startup via `start.py` (local dev or Cloudera AI)
- Toggle between **AWS Bedrock** and **Local LLM** (Ollama, vLLM, LM Studio, etc.)
- Pre-built static UI in `frontend/dist` for CAI deployments without Node.js on the cluster
- OpenAPI docs at `/docs`

## Quickstart

### One command (recommended)

From the repo root, this installs Python and npm dependencies if needed and starts both services:

```bash
cp backend/.env.example backend/.env   # optional: add AWS credentials
python start.py
```

- Frontend: [http://127.0.0.1:5173](http://127.0.0.1:5173) (or `CDSW_APP_PORT` on CML/CDSW)
- Backend API: [http://127.0.0.1:8000](http://127.0.0.1:8000) (or `CDSW_READONLY_PORT` on CML/CDSW)
- Swagger: http://127.0.0.1:{backend port}/docs

On Cloudera Machine Learning / CDSW, the platform sets:

- `CDSW_APP_PORT` → Vite frontend on `127.0.0.1`
- API traffic uses internal port **8000** between Vite and FastAPI (loopback-safe)

`CDSW_READONLY_PORT` is not used for in-container proxying — it can cause `EADDRNOTAVAIL` when Vite tries to reach `127.0.0.1:CDSW_READONLY_PORT`. Use the app URL for the UI; `/api` and `/docs` are proxied through Vite. For backend-only on CML, the API binds to `CDSW_READONLY_PORT`.

Options:

```bash
python start.py --skip-install   # skip pip/npm install (faster restarts)
```

Requires **Python 3.10+** and **Node.js/npm** for local dev.

### How start.py works

**On Cloudera AI** (no npm):

1. **Install** — `pip install` into `backend/venv`
2. **Serve** — FastAPI on `CDSW_APP_PORT` serves `/api` and the built UI from `frontend/dist`

**Local dev** (with npm):

1. **Install** — pip + npm
2. **Backend** — FastAPI on `127.0.0.1:8000`
3. **Frontend** — Vite on `127.0.0.1:5173` (proxies `/api` to port 8000)

### Deploying on Cloudera AI (CAI)

#### Architecture on CAI

```
Browser  -->  CAI App URL (*.cloudera.site)
                    |
                    v
    FastAPI @ 127.0.0.1:CDSW_APP_PORT
      - /api/*     -> Bedrock backend
      - /docs      -> Swagger
      - /*         -> pre-built React UI (frontend/dist)
```

No npm or Node.js is required on CAI. The React app is **built ahead of time** and committed in `frontend/dist`. FastAPI serves the UI and API on a single port.

#### Project setup (Workbench session)

Use a **Python 3** runtime. **Node.js is not required** on CAI — only Python dependencies are installed at startup.

```bash
pip install -r requirements.txt   # optional; start.py also installs into backend/venv
```

Set AWS credentials as **project or application environment variables** (never commit them):

| Variable                | Description                               |
| ----------------------- | ----------------------------------------- |
| `AWS_ACCESS_KEY_ID`     | AWS access key (or use instance/IAM role) |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key                            |
| `AWS_REGION`            | e.g. `us-east-1`                          |

#### Create the Application

In Cloudera AI → **Applications** → **New Application**:

| Field      | Value                      |
| ---------- | -------------------------- |
| **Script** | `entry.py` (or `start.py`) |
| **Kernel** | Python 3                   |

`entry.py` is a thin wrapper that calls `start.py`. On CAI the script will:

1. Install Python deps into `backend/venv`
2. Start FastAPI on `127.0.0.1:$CDSW_APP_PORT` (API + static UI from `frontend/dist`)

To rebuild the UI after frontend changes (on a machine with Node.js):

```bash
cd frontend && npm install && npm run build
```

Commit the updated `frontend/dist` folder.

#### Access on CAI

- **UI**: open the Application URL from the CAI dashboard
- **Swagger**: `{app-url}/docs`
- **Health**: `{app-url}/api/health`

| Variable        | Used for                       |
| --------------- | ------------------------------ |
| `CDSW_APP_PORT` | FastAPI bind port (API + UI)   |
| `CDSW_DOMAIN`   | Used by Vite in local dev only |

On CAI, `start.py` does **not** use npm. Python packages install into `backend/venv`. If a previous install failed, delete `backend/venv` and restart.

### Manual setup

#### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env         # Add your AWS credentials
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

#### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173)

## Architecture / Software Components

### Local development

```
┌─────────────────┐      /api/*       ┌──────────────────┐      boto3     ┌─────────────┐
│  React (Vite)   │ ────────────────► │  FastAPI Backend │ ─────────────► │ AWS Bedrock │
│  localhost:5173 │                   │  localhost:8000  │                │             │
└─────────────────┘                   └──────────────────┘                └─────────────┘
                                              │
                                              ▼
                                    Environment / IAM role
                                    (secrets never in frontend)
```

| Component | Role |
| --- | --- |
| `frontend/` | React + Vite chat UI; proxies `/api` to the backend in dev |
| `backend/` | FastAPI app, Bedrock and local LLM clients, model catalog |
| `start.py` / `entry.py` | Install deps and start the appropriate mode (local vs CAI) |
| `frontend/dist/` | Production static assets served by FastAPI on CAI |

## Target Audience

- ML engineers and data scientists evaluating Bedrock models from Cloudera AI
- Solution architects designing secure GenAI demos on Cloudera
- Sales engineers and developers who need a minimal full-stack Bedrock reference

## Repository Structure

| Path | Description |
| --- | --- |
| `backend/app/` | FastAPI routes, Bedrock/local LLM services, model catalog |
| `backend/.env.example` | Sample backend environment variables (copy to `.env` locally) |
| `frontend/src/` | React application source |
| `frontend/dist/` | Pre-built UI for Cloudera AI (rebuild with `npm run build`) |
| `start.py` | Unified launcher for local dev and CAI |
| `entry.py` | CAI application entrypoint (calls `start.py`) |
| `requirements.txt` | Top-level Python dependencies for workbench install |
| `PUBLISH.md` | Notes for syncing this repo from upstream Cloudera Applied AI |

Populate catalog and website fields in [`METADATA.yaml`](METADATA.yaml) when publishing as an official blueprint.

## Prerequisites

- Cloudera AI / CML workspace with Applications enabled (for CAI deployment), or a local machine for dev
- AWS account with Amazon Bedrock access and model entitlement in your chosen region
- AWS credentials via environment variables, `backend/.env`, or IAM role attached to the runtime
- **Local dev**: Python 3.10+, Node.js and npm
- **CAI only**: Python 3 runtime; Node.js not required on the cluster if `frontend/dist` is committed
- Optional: local OpenAI-compatible server (e.g. Ollama) for the Local LLM provider

## Hardware Requirements

| Deployment | Minimum |
| --- | --- |
| Launchable / demo (CAI Application) | Small Python application profile; no GPU required for Bedrock (inference is in AWS) |
| Local dev | Developer laptop; 4 GB+ RAM recommended for Vite + FastAPI |
| Local LLM mode | Depends on chosen model; GPU optional for Ollama/vLLM on your machine |

## Security

- **AWS credentials** are read only by the backend from environment variables or the default IAM credential chain (e.g. EC2/ECS instance role).
- **No secrets** are exposed to the React app or returned by `/api/config`.
- Copy `backend/.env.example` to `backend/.env` for local development — never commit `.env`.
- In production, prefer IAM roles over long-lived access keys.
- CORS is restricted to configured origins (`CORS_ORIGINS`).

## Switching Bedrock ↔ Local LLM

Use the **AWS Bedrock** / **Local LLM** toggle in the UI, or call the API:

```bash
# Switch to local OpenAI-compatible endpoint (Ollama, vLLM, LM Studio, etc.)
curl -X PUT http://localhost:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "local",
    "local_endpoint_url": "http://localhost:11434/v1",
    "local_model_id": "llama3.2",
    "local_api_token": "optional-bearer-token"
  }'

# Switch back to Bedrock
curl -X PUT http://localhost:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{"provider": "bedrock", "model_id": "anthropic.claude-haiku-4-5-20251001-v1:0"}'
```

Local API tokens are stored **only on the backend** and are never returned by `GET /api/config`.

Optional env vars: `LOCAL_LLM_BASE_URL`, `LOCAL_LLM_API_TOKEN`, `LOCAL_LLM_MODEL`, `DEFAULT_PROVIDER`.

## API Endpoints

| Endpoint      | Method | Description                           |
| ------------- | ------ | ------------------------------------- |
| `/api/health` | GET    | API and AWS credential status         |
| `/api/models` | GET    | List available Bedrock models         |
| `/api/config` | GET    | Current model and region (no secrets) |
| `/api/config` | PUT    | Update model or region                |
| `/api/chat`   | POST   | Send chat messages to Bedrock         |

### Example: update model

```bash
curl -X PUT http://localhost:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{"model_id": "anthropic.claude-haiku-4-5-20251001-v1:0"}'
```

### Example: chat

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello!"}]}'
```

## Configuration

Environment variables (backend only):

| Variable                | Description                          |
| ----------------------- | ------------------------------------ |
| `AWS_ACCESS_KEY_ID`     | Optional — use IAM role if unset     |
| `AWS_SECRET_ACCESS_KEY` | Optional                             |
| `AWS_SESSION_TOKEN`     | Optional — for temporary credentials |
| `AWS_REGION`            | Default AWS region                   |
| `DEFAULT_MODEL_ID`      | Initial Bedrock model                |
| `CORS_ORIGINS`          | Allowed frontend origins             |

## Supported Models

Anthropic Claude 4.5, Amazon Nova, Titan, Meta Llama 3, and Mistral models are pre-configured. EOL/Legacy models are excluded automatically. Add more in `backend/app/models_catalog.py`.

## Documentation

- Interactive API reference: `/docs` on the running application
- [PUBLISH.md](PUBLISH.md) — upstream sync and publishing notes
- [Amazon Bedrock documentation](https://docs.aws.amazon.com/bedrock/)
- [Cloudera AI documentation](https://docs.cloudera.com/)
