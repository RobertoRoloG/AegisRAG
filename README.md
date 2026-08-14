<h1 align="center">AegisRAG</h1>

<p align="center">
  <img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Next.js-000000?style=flat-square&logo=nextdotjs&logoColor=white" alt="Next.js" />
  <img src="https://img.shields.io/badge/TypeScript-3178C6?style=flat-square&logo=typescript&logoColor=white" alt="TypeScript" />
  <img src="https://img.shields.io/badge/Celery-356C40?style=flat-square&logo=celery&logoColor=white" alt="Celery" />
  <img src="https://img.shields.io/badge/PostgreSQL-4169E1?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL" />
  <img src="https://img.shields.io/badge/Qdrant-FF4154?style=flat-square&logo=qdrant&logoColor=white" alt="Qdrant" />
  <img src="https://img.shields.io/badge/Redis-DC382D?style=flat-square&logo=redis&logoColor=white" alt="Redis" />
  <img src="https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker" />
</p>

## Overview
AegisRAG is a production-grade, full-stack Corrective Retrieval-Augmented Generation (CRAG) system designed to mitigate hallucination and context irrelevance in LLM applications. Built on a decoupled microservices architecture, it orchestrates hybrid vector-lexical queries, context re-ranking, and dynamic self-correction loops to ensure accurate, verified context feeds generation.

## Tech Stack
*   **Backend:** Python 3.11+, FastAPI (ASGI Framework), Celery (Distributed Task Queue), SQLAlchemy 2.0 (Async ORM), FastEmbed (Local Embeddings & Reranking), PyPDF (Document Parsing).
*   **Frontend:** Next.js 16 (App Router), TypeScript, React 19, Tailwind CSS 4, Lucide React.
*   **Databases & Caches:** PostgreSQL 16 (Relational Metadata & History), Qdrant v1.18.2 (Vector Database supporting dense/sparse hybrid search), Redis 7 (Asynchronous Message Broker & Cache).
*   **Infrastructure & Deployment:** Docker, Docker Compose.

## Key Features
*   **Corrective RAG (CRAG) Pipeline:** Self-corrective pipeline with automated query rewriting and dynamic relevance thresholding (default `0.35` Cross-Encoder score) to filter out hallucinated context.
*   **Hybrid Semantic-Lexical Search:** Combines dense vectors (embedding-based search) and sparse vectors (BM25 keyword search) natively within Qdrant.
*   **Two-Stage Retrieval & Re-ranking:** Integrates a second-pass context optimization layer powered by `BAAI/bge-reranker-base`.
*   **Asynchronous Ingestion Queue:** Decoupled document processing (PDF parsing and chunking) using Celery background workers to keep API endpoints non-blocking.
*   **Multi-LLM Integration:** Pluggable support for local LLMs via Ollama (e.g., Llama 3) or commercial APIs including OpenAI and Groq.
*   **Session & History Tracking:** Persistent relational storage for chat sessions, message histories, and extraction metadata.

## Prerequisites
*   **OS:** Linux, macOS, or Windows (WSL 2 or PowerShell recommended)
*   **Python:** `v3.11` or higher
*   **Node.js:** `v20.x` or higher (with `npm` package manager)
*   **Docker:** Engine `v20.10+` and Docker Compose `v2.0+`

## Installation & Setup
1.  **Clone the Repository:**
    ```bash
    git clone https://github.com/RobertoRoloG/AegisRAG.git
    cd AegisRAG
    ```

2.  **Configure Environment Variables:**
    Copy the template file to `.env` and adjust the configuration as required:
    ```bash
    cp .env.example .env
    ```
    The main environment variables defined in `.env` are:
    *   `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB`: PostgreSQL credentials.
    *   `POSTGRES_PORT`: PostgreSQL host port (default `5433`).
    *   `QDRANT_PORT` / `QDRANT_GRPC_PORT`: Qdrant host ports (default `6333`/`6334`).
    *   `REDIS_PORT` / `REDIS_URL`: Redis configuration.
    *   `LLM_PROVIDER`: Pluggable LLM provider (`ollama`, `groq`, or `openai`).
    *   `LLM_MODEL`: Target model (e.g., `llama-3.1-8b-instant`, `llama3`).
    *   `GROQ_API_KEY` / `OPENAI_API_KEY`: API keys for cloud model providers.
    *   `CRAG_RELEVANCE_THRESHOLD`: Document evaluation relevance score threshold (default `0.35`).

3.  **Start Services (Infrastructure Stack):**
    Spin up PostgreSQL, Qdrant, and Redis containers:
    ```bash
    docker compose up -d
    ```

4.  **Set Up Backend (FastAPI & Celery):**
    Initialize a virtual environment, activate it, and install Python dependencies:
    ```bash
    cd backend
    python -m venv .venv
    
    # Windows (PowerShell):
    .venv\Scripts\Activate.ps1
    # Linux / macOS:
    source .venv/bin/activate

    pip install --upgrade pip
    pip install -r requirements.txt
    ```

5.  **Set Up Frontend (Next.js):**
    Install client node packages:
    ```bash
    cd ../frontend
    npm install
    ```

## Usage / Execution
1.  **Verify Service Infrastructure:**
    Ensure database, vector store, and broker containers are healthy:
    ```bash
    docker compose ps
    ```

2.  **Run Backend API Server:**
    From the `backend` directory, activate the virtual environment and launch Uvicorn:
    ```bash
    cd backend
    # Activate virtual environment if not done already
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
    ```

3.  **Run Celery Ingestion Worker:**
    In a separate terminal session, navigate to the `backend` directory, activate the virtual environment, and run:
    ```bash
    # Windows (PowerShell):
    .venv\Scripts\celery.exe -A app.workers.celery_app worker --loglevel=info --pool=solo
    # Linux / macOS:
    celery -A app.workers.celery_app worker --loglevel=info
    ```

4.  **Run Frontend Client:**
    From the `frontend` directory, start the Next.js development server:
    ```bash
    cd frontend
    npm run dev
    ```

5.  **Access Main Endpoints:**
    *   **Frontend UI:** [http://localhost:3000](http://localhost:3000)
    *   **Swagger API Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)
    *   **Backend Health Check:** [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health)

## Roadmap
- [ ] Add support for additional file formats (`.docx`, `.md`, `.txt`, `.html`).
- [ ] Implement Server-Sent Events (SSE) for streaming model generation.
- [ ] Integrate JWT authentication and Role-Based Access Control (RBAC).
- [ ] Optimize Docker configuration using multi-stage production builds.
- [ ] Integrate retrieval evaluation frameworks (Ragas / TruLens) to monitor retrieval quality.
