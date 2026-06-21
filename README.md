# Health Insurance Claim Adjudication System 🏥

An end-to-end, AI-powered system designed to ingest complex medical policy documents, convert them into a structured and deterministic ruleset, and autonomously adjudicate medical claims with a line-by-line financial audit trail.

---

## Key Concepts

This project bridges the gap between unstructured, ambiguous legal policy documents and strict, deterministic financial calculations. It operates in two distinct phases:

### 1. Ingestion Phase (AI-Powered) 
The system takes an unstructured Policy Wording PDF and uses OCR (Docling) alongside Large Language Models (LLMs) to extract a structured `PolicyRuleSet`.
- **Extraction**: It accurately extracts Coverage Rules, Deductibles, Exclusions, and Endorsements.
- **Normalisation**: It calculates percentages (e.g., turning "10% coinsurance" into a strict `0.90` insurer share) and maps medical jargon to standardised `benefit_codes`.
- **Storage**: The resulting ruleset is saved directly to a PostgreSQL database, ready to be used by the adjudication engine.

### 2. Adjudication Phase (Deterministic Engine) 
Unlike the ingestion phase, **this phase uses zero AI**. It is a pure, deterministic Python engine.
- **Ledger Tracking**: Tracks limits across claims (e.g., Annual Aggregate Limits and specific Sub-limits).
- **Sequential Application**: Sequentially applies Exclusions -> Benefit Limits -> Deductibles -> Coinsurance -> Penalties.
- **Auditability**: Every financial change generates an `AuditLine`, providing absolute transparency on exactly how a claim payout was calculated.

---

##  Architecture

The system is built as a microservices architecture using Docker Compose:

1. **Postgres (`polices_db`)**: Stores the extracted rulesets securely.
2. **Ingestion API (`ingestion-api`)**: FastAPI application on port `8080` handling the PDF parsing and AI extraction.
3. **Adjudication API (`adjudication-api`)**: FastAPI application on port `8081` running the deterministic rules engine against incoming claims.
4. **Streamlit UI (`streamlit-ui`)**: A frontend on port `8501` to easily interact with the APIs.

---

##  Setup & Usage

### 1. Prerequisites
- Docker and Docker Compose installed.
- An OpenAI API Key (or equivalent compatible API).

### 2. Configuration
Create a `.env` file in the root directory:
```env
LLM_API_KEY="your-api-key-here"
# LLM_API_URL="" # Set this if you use an alternative endpoint like vLLM
LLM_LARGE_MODEL="gpt-4o"
LLM_SMALL_MODEL="gpt-4o-mini"
DATABASE_URL="postgresql+asyncpg://admin:admin@postgres:5432/policies"
```

### 3. Start the Platform
Run the following command to build the images and boot up all four containers:
```bash
docker-compose up -d --build
```

> **First boot takes ~30-60 seconds.** The Ingestion and Adjudication containers load heavy ML models (Docling/RapidOCR/PyTorch) on startup. Wait until all 4 containers show **Running** in Docker Desktop or `docker ps` before opening the UI.

### 4. Using the System
Once the containers are running, navigate to the Streamlit UI in your browser:
 **[http://localhost:8501](http://localhost:8501)**

**Step 1: Ingest a Policy**
- Go to the **Ingestion Dashboard** page.
- Enter a unique `Policy ID` (e.g., `POL-2026-A1`).
- Upload your Policy Wording PDF.
- The system will process it and store the rules in Postgres.

**Step 2: Adjudicate a Claim**
- Switch to the **Claims Adjudication** page.
- Enter the same `Policy ID`.
- Upload a Medical Invoice PDF.
- The engine will adjudicate the claim and present a highly detailed financial breakdown and step-by-step audit trail.

---

##  Tech Stack
- **Backend Framework**: FastAPI
- **Database**: PostgreSQL
- **Frontend**: Streamlit
- **PDF Parsing**: Docling / RapidOCR
- **AI Extraction**: `instructor` with OpenAI
- **Package Management**: `uv`

docker exec -it polices_db psql -U admin -d policies -c "TRUNCATE TABLE policy_rulesets;";     