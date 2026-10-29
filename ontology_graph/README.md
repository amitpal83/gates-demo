# ontology_graph — LIC policy pipeline

Self-contained and independent of `gates_ai_common` and `rag_ingestion`. Drop a PDF into the MinIO `licdocuments` bucket and:

```
MinIO bucket licdocuments (*.pdf; working files go to bucket lic-pipeline)
  -> lic-webhook -> Airflow DAG lic_policy_ingestion
       stage -> parse (LlamaParse) -> chunk -+-> build_ontology -> GraphDB (repository lic_policy)
                                             +-> embed -> Qdrant (collection lic_policy_docs)
PostgreSQL policy records + GraphDB ontology facts + Qdrant passages -> Policy Data Query Agent (port 8503)
```

## Layout

| Path | What it is |
|---|---|
| `ontology/schema.py` | The ontology schema (classes, relations, data properties); generates the Turtle loaded into GraphDB. `python -m ontology_graph.ontology.schema` prints it. |
| `ontology/facts.py` | Validates LLM-extracted facts against the schema, renders instance Turtle |
| `ontology/queries.py` | SPARQL used at question time |
| `pipeline/ingest.py`, `pipeline/ontology_build.py` | The DAG's task bodies |
| `dags/lic_policy_ingestion.py` | The DAG (picked up via `rag_ingestion/dags/lic_policy_ingestion_loader.py`) |
| `webhook/app.py` | MinIO event -> Airflow REST trigger |
| `agent.py`, `ui/` | Question answering and the Streamlit app |
| `clients/` | MinIO, Qdrant, GraphDB, PostgreSQL |
| `hooks.py` | Empty guardrail hooks (document / question / answer) for Portkey etc. |
| `postgres/init.sql` | Schema plus two fictional sample policies |

## Configuration

Append to `rag_ingestion/.env` on the box (the compose project reads that file):

```
LIC_POSTGRES_PASSWORD=<choose one>          # required
# LIC_WEBHOOK_SHARED_SECRET=                # optional; defaults to RAG_WEBHOOK_SHARED_SECRET
# GRAPHDB_IMAGE=ontotext/graphdb:10.6.4     # optional
# GRAPHDB_JAVA_OPTS=-Xms1g -Xmx2g           # optional; size to the instance
# LIC_LLM_MODEL=gpt-4o-mini                 # optional
```

Portkey later: the code uses the OpenAI SDK, which reads `OPENAI_BASE_URL`. Add that variable to the `lic-ui` service (and the Airflow services for the DAG), and set `LIC_LLM_DEFAULT_HEADERS` to the JSON headers Portkey needs. Fill in `hooks.py` for guardrails.

## Run (from the repo root, on the box)

One command starts everything (shared infra, Airflow, LIC services), re-runs the MinIO setup and verifies the DAG loaded:

```bash
bash ontology_graph/deploy.sh --pull     # --pull does git pull --ff-only first
bash ontology_graph/deploy.sh status     # show service state
bash ontology_graph/deploy.sh down       # stop only the LIC services
```

The manual equivalent:

```bash
docker compose -f rag_ingestion/docker-compose.yml -f ontology_graph/docker-compose.yml \
  up -d --build graphdb policy-postgres lic-webhook lic-minio-init lic-ui
```

`lic-minio-init` creates the `licdocuments` and `lic-pipeline` buckets and the event rule, and restarts MinIO only if the webhook target is new. The existing `gates-rag-ingestion` bucket and `incoming/` flow are untouched. Re-running it is safe.

Services: GraphDB Workbench on `127.0.0.1:7200` (use `ssh -L 7200:localhost:7200 ...`), the UI on port `8503` (open it in the security group), PostgreSQL internal only.

## Try it

1. Upload the LIC PDF to the `licdocuments` bucket in the MinIO console (port 9001).
2. Watch `lic_policy_ingestion` in the Airflow UI (port 8080) until it is green.
3. Open the UI, tab **Ontology**, to see the extracted ontology; use the GraphDB Workbench for SPARQL and the class hierarchy.
4. Tab **Ask about a policy**: pick `LIC-NP-0001` and ask, for example, "Can I withdraw part of my fund now?"

## Not included yet

- No guardrails: no document/PII scan, input validation, topic or output checks. The hooks in `hooks.py` are where they plug in.
- No tracing or cost logging.
- The sample policies in `postgres/init.sql` are fictional.
