# RAG PDF ingestion pipeline

This stack backs the LlamaIndex-backed RAG demo: an Airflow-orchestrated
pipeline that turns a PDF dropped into a MinIO bucket into embedded chunks in
Qdrant, ready for query-time retrieval from the "LlamaIndex RAG" Streamlit
page (`pages/2_LlamaIndex_RAG.py`).

Pipeline shape: MinIO (raw PDF landing zone, `incoming/` prefix) -> a webhook
notification fires on every new `.pdf` -> `rag-webhook` triggers the
`rag_pdf_ingestion` Airflow DAG via the REST API -> LlamaParse (PDF ->
markdown) -> chunking -> metadata + `gates_ai_common` safety gates ->
embeddings -> Qdrant load -> ingestion-quality evaluation.

This is a separate pipeline from the existing mocked `agents/rag_flow.py`
demo.

**Fully additive.** This does not touch `agents/`, `streamlit_app.py`,
`litellm/` (its own separate stack), `gates_ai_common/`'s core behavior (only
imports it read-only, over a bind mount), or any of the existing lines in the
root `requirements.txt` (it adds exactly three new lines at the end for the
query-time Streamlit page's in-venv dependencies -- see that file). Nothing
here is required for the rest of the app to keep working.

## Prerequisites

- Docker + Docker Compose v2 (`docker compose version`). See
  `litellm/README.md`'s "Install Docker" section if you need to set this up
  on a fresh Ubuntu box -- the same steps apply here.
- An OpenAI API key (for embeddings) and a LlamaParse API key from
  [cloud.llamaindex.ai](https://cloud.llamaindex.ai) (for PDF parsing).
- At least a few GB of free RAM/disk -- this stack runs Airflow (webserver +
  scheduler + Postgres), MinIO, Qdrant, and the webhook service all at once.
  Comfortable on a `t3.medium`-class box or larger, similar to the sizing
  note in `litellm/README.md`.

## 1. Configure secrets

    cd rag_ingestion
    cp env.sample .env

Generate the secrets this stack owns (don't leave `env.sample`'s placeholders
in `.env`):

    openssl rand -hex 24   # MINIO_ROOT_PASSWORD
    openssl rand -hex 24   # AIRFLOW_POSTGRES_PASSWORD
    openssl rand -hex 24   # AIRFLOW_API_PASSWORD
    openssl rand -hex 24   # AIRFLOW_WEBSERVER_SECRET_KEY
    openssl rand -hex 24   # RAG_WEBHOOK_SHARED_SECRET

    # AIRFLOW_FERNET_KEY is NOT an openssl-hex value -- it must be a valid
    # Fernet key:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

    nano .env

Fill in:
- `OPENAI_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`,
  `LANGFUSE_HOST` -- copy these from the root `.env` (`gates_ai_lld/.env`);
  same values, not new ones. Langfuse vars are optional, leave blank to skip
  the ingestion-side trace.
- `LLAMA_CLOUD_API_KEY` -- from your LlamaParse account.
- `MINIO_ROOT_PASSWORD` -- **set this to its real value before the first
  `docker compose up -d`**, same reasoning as `litellm/README.md`'s note on
  `POSTGRES_PASSWORD`: MinIO only applies root credentials when it
  initializes its data volume on first start, so changing it later means
  either reconfiguring MinIO's user store or wiping the `minio_data` volume.

## 2. Start the stack

    docker compose up -d
    docker compose ps

You should see `minio`, `qdrant`, `airflow-postgres`, `airflow-webserver`,
`airflow-scheduler`, and `rag-webhook` all "Up" (`minio-init` exits after it
finishes bootstrapping the bucket/webhook -- that's expected, check its logs
if something downstream looks unconfigured):

    docker compose logs minio-init

## 3. Health checks

    curl http://localhost:9000/minio/health/live      # MinIO API
    curl http://localhost:6333/                        # Qdrant (127.0.0.1 only)
    curl http://localhost:8080/health                  # Airflow webserver

`rag-webhook` has no host port binding (internal-only, reached by MinIO over
the compose network at `http://rag-webhook:8090`) -- check it's alive via
`docker compose logs rag-webhook` instead of curling it from the host.

## 4. Upload a PDF to kick off ingestion

Open the MinIO console at `http://<host>:9001`, log in with
`MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD`, open the `MINIO_BUCKET` bucket, and
upload a PDF into the `incoming/` prefix. That upload firing a
`s3:ObjectCreated:*` event (filtered to the `incoming/` prefix and `.pdf`
suffix) is what triggers `rag-webhook`, which in turn triggers the
`rag_pdf_ingestion` DAG via the Airflow REST API.

## 5. Watch the DAG run

Open the Airflow UI at `http://<host>:8080`, log in with
`AIRFLOW_API_USERNAME`/`AIRFLOW_API_PASSWORD` (from your `.env`), and find
`rag_pdf_ingestion` in the DAGs list. Each run's task graph shows the
parse -> chunk -> metadata/gate -> embed -> load -> evaluate stages.

## 6. Inspect the results

MinIO stages intermediate artifacts per document under the bucket, e.g.:

    raw/<doc_id>/...          # the original uploaded PDF
    parsed/<doc_id>/...       # LlamaParse markdown output
    chunked/<doc_id>/...      # chunked text
    metadata/<doc_id>/...     # extracted/derived metadata, gate results
    embeddings/<doc_id>/...   # embedding vectors (if staged before Qdrant load)

Browse these via the same MinIO console used for upload. In Qdrant, check
the `gates_rag_docs` collection (or `gates_rag_docs_dev384` for a
lower-dimension dev/test collection) via the Qdrant dashboard at
`http://localhost:6333/dashboard` (only reachable from the host itself, since
that port is bound to `127.0.0.1`) or the `qdrant-client` API.

## 7. Query it

Once a document has been ingested, run the existing Streamlit app and open
the "LlamaIndex RAG" page (`pages/2_LlamaIndex_RAG.py`):

    streamlit run streamlit_app.py

It runs in-process in the existing root venv (not in Docker) and reads
from the same Qdrant instance via `QDRANT_URL`/the collection names
above. The pipeline (`rag_ingestion/query_engine.py`) runs:

1. **Understand Query** -- validate the question (llm-guard/regex), then
   an LLM call rewrites/expands it and extracts metadata filters
   (`pdf_type`/`author`/`owner`) as JSON; falls back to a regex-based
   filter detector (`type:policy`, `author:jane`, `owner:dost`, etc.)
   when running on the mock LLM backend.
2. **Retrieve** -- embeds the (expanded) question as both a dense vector
   and a BM25-style sparse vector (`common/sparse_vectors.py`), then a
   *single* Qdrant `query_points` call fuses dense + sparse candidates via
   RRF and applies the detected metadata filter -- this is real
   dense+sparse hybrid search, not an approximation; see
   `clients/qdrant_client_helper.py`'s `hybrid_search()`.
3. **Rerank & Assemble** -- a cross-encoder (`sentence-transformers`
   `CrossEncoder`, downloaded on first use) reranks the fused candidates
   down to the final top-k, falling back to a lexical-overlap boost if the
   model can't be loaded (e.g. no network). Builds the prompt with
   numbered `[1]`/`[2]` citation markers tied to each source's metadata.
4. **Generate** -- one LLM call over the assembled, cited context.
5. **Respond** -- the output-safety guardrail (`gates_ai_common.guardrails`)
   is a blocking check right here (an unsafe answer never reaches the
   caller); the answer + citations are then returned immediately.
   Quality evaluation and cost/latency logging run **after** that, in a
   background thread (fire-and-forget) -- see `_evaluate_and_log` --
   feeding `gates_ai_common`'s observability log / Langfuse without
   adding latency to the response.

LlamaIndex itself is used on the ingestion side
(`tasks/chunk_document.py`'s `SentenceSplitter`), not for query-time
retrieval -- this page needs no dependency beyond what's already in the
root `requirements.txt`.

**Schema note:** Qdrant collections created before hybrid search existed
used a single unnamed dense vector; this pipeline now requires two named
vectors per point (`"dense"` + `"sparse"`, the latter with Qdrant's
`Modifier.IDF`). If you ever ingested a document against an older
collection, drop it (`docker exec` into `qdrant` or use its dashboard)
before re-ingesting -- `ensure_collection` only creates a collection that
doesn't exist yet, it doesn't migrate one.

This same page is also served over Docker by the `streamlit` service in
`docker-compose.yml` (build context: repo root,
`docker/Dockerfile.streamlit`) -- that's what backs the AWS deployment's
public port 8501 (see `deploy/rag_ingestion_aws/README.md`), since an EC2
box has no pre-existing venv to run `streamlit run` in directly.

## Exposing MinIO to the internet

Unlike `litellm/docker-compose.yml`'s port 4000 (which you opt into exposing
by editing a security group), MinIO's ports 9000/9001 in this stack are
**bound to all interfaces by default**, not just `127.0.0.1` -- this was a
deliberate, explicit request so PDFs can be uploaded via the console/API
from anywhere, not something you need to turn on separately. That means
anyone who can reach the host on those ports and guesses/leaks
`MINIO_ROOT_PASSWORD` has full read/write access to every staged artifact in
the bucket, including raw source PDFs. This is **not hardened**: fine for a
throwaway exploration box, not something to leave running long-term or point
at sensitive documents. If you want to tighten it, the change that matters
most is rebinding both port lines in `docker-compose.yml` to
`127.0.0.1:9000:9000` / `127.0.0.1:9001:9001` and reaching the console over an
SSH tunnel instead, mirroring how `litellm/README.md` tightens its own proxy
port back up.

## Known limitations / things to verify against your installed versions

- **Hybrid search needs `qdrant-client`/Qdrant server >= 1.10** (Query API,
  sparse vectors, `Modifier.IDF`). Both `requirements.txt` files pin
  `qdrant-client>=1.10.0`; the server image is already pinned to `v1.12.1`
  in `docker-compose.yml`.
- **Cross-encoder rerank downloads a model on first use**
  (`cross-encoder/ms-marco-MiniLM-L-6-v2`, via `sentence-transformers`) --
  the query-side host/container needs network access to Hugging Face the
  first time a query runs (cached after that). Falls back to a lexical
  rerank automatically if the download/load fails, so this degrades
  gracefully rather than breaking the page.
- **`mc` CLI event-notification syntax.** The `minio-init` service's
  bootstrap script uses `mc admin config set local notify_webhook:ragwebhook
  endpoint="..."`, `mc admin service restart local`, and `mc event add
  local/$MINIO_BUCKET arn:minio:sqs::ragwebhook:webhook --prefix incoming/
  --suffix .pdf --event put`. These are written against the documented `mc`
  interface at the time of writing; `minio/mc:latest` is intentionally
  unpinned (MinIO doesn't publish stable version tags for the client the way
  it does the server), so this surface can shift under you between runs --
  spot-check the actual subcommand names/flags against whatever version gets
  pulled, same "verify before you build on it" caution as
  `litellm/README.md`'s closing section.
- **LlamaParse SDK's file-input API.** The exact call shape for submitting a
  PDF to LlamaParse (path vs. bytes vs. presigned URL, sync vs. async job
  polling) should be checked against the installed `llama-parse` package
  version before assuming the ingestion tasks' usage is exactly right.
- **Airflow 2.10.x REST API auth model.** `rag-webhook` triggers DAG runs via
  Airflow's REST API using `AIRFLOW_API_USERNAME`/`AIRFLOW_API_PASSWORD`
  (basic auth). Confirm this is still the active auth backend for your
  Airflow config -- 2.x's API auth backends are configurable
  (`AUTH_BACKEND`/FAB-based), and the default can vary by base image/version.
