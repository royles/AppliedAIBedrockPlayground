# Bedrock Playground

A lightweight playground for experimenting with AWS Bedrock models. The React frontend provides a simple chat UI; the FastAPI backend handles all AWS connectivity and keeps credentials secure.

## Architecture

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



## Security

- **AWS credentials** are read only by the backend from environment variables or the default IAM credential chain (e.g. EC2/ECS instance role).
- **No secrets** are exposed to the React app or returned by `/api/config`.
- Copy `backend/.env.example` to `backend/.env` for local development — never commit `.env`.
- In production, prefer IAM roles over long-lived access keys.
- CORS is restricted to configured origins (`CORS_ORIGINS`).



## Quick Start



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

Requires **Python 3.10+** and **Node.js/npm**.

### How start.py works

**On Cloudera AI** (no npm):

1. **Install** — `pip install -r requirements.txt` into the **platform Python environment** (no `backend/venv` on CAI)
2. **Serve** — FastAPI on `CDSW_APP_PORT` serves `/api` and the built UI from `frontend/dist`

**Local dev** (with npm):

1. **Install** — pip + npm
2. **Backend** — FastAPI on `127.0.0.1:8000`
3. **Frontend** — Vite on `127.0.0.1:5173` (proxies `/api` to port 8000)



## Deploying on Cloudera AI (CAI)



### Architecture on CAI

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

### 1. Project setup (Workbench session)

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




### 2. Create the Application

In Cloudera AI → **Applications** → **New Application**:


| Field      | Value                      |
| ---------- | -------------------------- |
| **Script** | `start.py`                 |
| **Kernel** | Python 3                   |


On CAI the script will:

1. Install Python deps into the **active session / application Python environment**
2. Start FastAPI on `127.0.0.1:$CDSW_APP_PORT` (API + static UI from `frontend/dist`)

To rebuild the UI after frontend changes (on a machine with Node.js):

```bash
cd frontend && npm install && npm run build
```

Commit the updated `frontend/dist` folder.

### 3. Access

- **UI**: open the Application URL from the CAI dashboard  
- **Swagger**: `{app-url}/docs`  
- **Health**: `{app-url}/api/health`



### CAI environment variables (set by platform)


| Variable        | Used for                       |
| --------------- | ------------------------------ |
| `CDSW_APP_PORT` | FastAPI bind port (API + UI)   |
| `CDSW_DOMAIN`   | Used by Vite in local dev only |


On CAI, `start.py` does **not** use npm or `backend/venv`; it uses the interpreter already provided by the platform (`sys.executable`). If installs fail, fix the project/session Python environment or re-run `pip install -r requirements.txt` in a Workbench terminal.

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