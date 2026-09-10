# LiteLLM Proxy demo (SQL Agent LiteLLM)

This stack backs `agents/sql_agent_litellm.py` and the "SQL Agent LiteLLM"
page in the Streamlit app (`pages/1_SQL_Agent_LiteLLM.py`). It's the same
SQL-writing agent as `agents/sql_agent.py`, but routed through a LiteLLM
Proxy instead of calling OpenAI directly -- so model routing, cross-provider
fallback, PII detection, guardrails, caching, and spend tracking all live in
the gateway instead of in `gates_ai_common`.

This is fully additive: nothing here changes `agents/sql_agent.py`,
`gates_ai_common/`, `streamlit_app.py`, or `requirements.txt`. If the stack
isn't running (or the env vars below aren't set), `agents/sql_agent_litellm.py`
falls back to the same offline `MockLLM` the original SQL agent uses.

## Running on an Ubuntu EC2 instance

This is written for the case where the repo + Python venv are already on
the box and only the LiteLLM stack is left to set up. All container ports
in `litellm/docker-compose.yml` are bound to `127.0.0.1` only, so the app
(running outside Docker, in your existing venv) talks to the proxy at
`http://localhost:4000` exactly as it would locally -- Postgres/Redis/
Presidio are never reachable from outside the box, and no security-group
change is needed for the stack itself.

**Instance size** -- Presidio's analyzer image bundles an NLP model and is
not lightweight; running LiteLLM + Postgres + Redis + both Presidio
containers + your Streamlit app on one box wants at least a `t3.medium`
(2 vCPU / 4 GB RAM). `t2.micro`/`t3.micro` will likely swap or OOM.

### 1. Install Docker

    sudo apt-get update
    sudo apt-get install -y docker.io
    sudo systemctl enable --now docker
    sudo usermod -aG docker $USER
    newgrp docker   # or log out/in over SSH -- either way, needed for group membership to apply

`docker-compose-plugin` is not in Ubuntu's default apt repos (it lives in
Docker's own repo), so install the Compose v2 CLI plugin as a binary
instead -- works regardless of where your Docker Engine package came from:

    mkdir -p ~/.docker/cli-plugins
    ARCH=$(uname -m)   # x86_64 or aarch64
    curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-${ARCH}" \
      -o ~/.docker/cli-plugins/docker-compose
    chmod +x ~/.docker/cli-plugins/docker-compose

Verify: `docker --version && docker compose version`.

### 2. Configure secrets

    cd litellm
    cp env.sample .env

Generate real values for the two secrets this stack owns (don't leave the
placeholders in `env.sample` as-is):

    openssl rand -hex 24   # run once for LITELLM_MASTER_KEY
    openssl rand -hex 24   # run again for POSTGRES_PASSWORD

    nano .env

Fill in:
- `OPENAI_API_KEY` -- same one the app's root `.env` already uses.
- `GEMINI_API_KEY` -- copy the value from the root `.env`'s `GOOGLE_API_KEY`.
  LiteLLM's `gemini/` provider reads this specific name, not `GOOGLE_API_KEY`.
- `LITELLM_MASTER_KEY` -- one of the random strings above. Safe to change
  later too: it's read fresh from the environment on every proxy startup
  (`docker compose restart litellm-proxy` picks up a new value immediately,
  no migration, and it won't invalidate virtual keys already created).
- `POSTGRES_PASSWORD` -- the other random string. **Set this to its real
  value now, before the first `docker compose up -d`.** Postgres only
  applies this env var when it initializes its data volume on first start;
  changing it afterwards leaves the old password baked into the volume and
  LiteLLM's `DATABASE_URL` (which reads the new value) fails to
  authenticate. Fixing that later means either `ALTER USER litellm WITH
  PASSWORD '...'` inside the Postgres container, or wiping the
  `litellm_pgdata` volume and losing spend/budget history -- cheaper to get
  it right up front.
- `LANGFUSE_*` -- optional, leave blank to skip the gateway-side Langfuse trace.

### 3. Start the stack

    docker compose up -d
    docker compose ps                     # all 4 services should show "Up"
    docker compose logs -f litellm-proxy   # watch it boot, Ctrl-C once it's serving

Quick health check from the box itself:

    curl http://localhost:4000/health/liveliness

### Admin UI

The proxy serves an admin UI at `/ui` for managing keys/models/spend
visually instead of via `curl`. Log in with:
- Username: `admin`
- Password: your `LITELLM_MASTER_KEY` value

(Override with `UI_USERNAME`/`UI_PASSWORD` env vars if you'd rather not use
the master key as a login password.) If `/ui` 404s, it's a known rough edge
with certain LiteLLM image builds/tags -- the UI is optional for this demo;
everything in the demo script below works via `curl` and the Streamlit
page's own gateway-status panel regardless.

#### Exposing the UI to the internet (POC only)

`docker-compose.yml` currently binds `litellm-proxy`'s port 4000 to all
interfaces (`"4000:4000"`, not `127.0.0.1:4000:4000`), and this section
assumes that's what you want -- browse straight to
`http://<ec2-public-ip>:4000/ui` with no SSH tunnel. This is **not
hardened**: the login is your master key sent over plain HTTP with no IP
restriction. Fine for a throwaway exploration box; don't leave it running
this way, and don't reuse this master key anywhere else once you tear the
instance down.

To make that reachable, open the port in the EC2 security group:

    aws ec2 authorize-security-group-ingress \
      --group-id <your-sg-id> \
      --protocol tcp --port 4000 --cidr 0.0.0.0/0

(or via the Console: EC2 -> Security Groups -> your instance's SG -> Edit
inbound rules -> Add rule -> Custom TCP, port 4000, source `0.0.0.0/0`.)

If you'd rather not hunt for a hardened setup later, the two changes that
matter most whenever you do want to tighten this back up are: rebind the
port to `127.0.0.1:4000:4000` in `docker-compose.yml`, and restrict the
security-group rule's source to your own IP instead of `0.0.0.0/0`.

### 4. Create a virtual key

Easiest run from the same box, so `localhost` always resolves regardless of
how port 4000 is currently bound:

    source .env   # so $LITELLM_MASTER_KEY is set in this shell
    curl -X POST http://localhost:4000/key/generate \
      -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
      -H "Content-Type: application/json" \
      -d '{"models": ["gates-sql-writer"], "max_budget": 5}'

Copy the `key` value from the response.

### 5. Point the app at the proxy

Add to the app's root `.env` (`gates_ai_lld/.env`, not `litellm/.env`):

    LITELLM_PROXY_URL=http://localhost:4000
    LITELLM_VIRTUAL_KEY=<key from step 4>
    LITELLM_MASTER_KEY=<same master key as litellm/.env>   # optional, only needed for the spend/budget panel

### 6. Sanity-check before touching the UI

    cd ..    # back to gates_ai_lld/
    source venv/bin/activate
    python -m agents.sql_agent_litellm "What is the total budget by region?"

Look for `[backend] litellm-proxy` and `[resolved_model]` showing the real
OpenAI model in the printed stage trace -- that confirms the whole chain
(venv -> proxy -> OpenAI, with Redis/Postgres/Presidio/guardrail all in the
loop) before bringing Streamlit into it.

### 7. Run Streamlit persistently

    tmux new -s streamlit
    streamlit run streamlit_app.py --server.address 0.0.0.0 --server.port 8501
    # Ctrl-B then D to detach; `tmux attach -t streamlit` to come back

Reach it either via an SSH tunnel (`ssh -L 8501:localhost:8501 <user>@<ec2-host>`
from your laptop, then browse `localhost:8501` -- no security-group change),
or by opening port 8501 to your own IP in the security group. Either way,
open the "SQL Agent LiteLLM" page in the sidebar -- Streamlit auto-discovers
`pages/1_SQL_Agent_LiteLLM.py`, no other file needed to change.

The demo script below is identical whether the stack runs on a laptop or on
EC2.

## Demo script

1. **Model + fallback** -- ask a normal question; the stage trace's
   `resolved_model` shows the OpenAI deployment served it. Force a fallback
   with LiteLLM's testing flag (pass `extra_body={"mock_testing_fallbacks": true}`
   on a direct call to the proxy) and confirm `resolved_model` switches to
   the Gemini deployment -- a genuine cross-provider failover.
2. **Caching** -- click "Run", then "Run again (cache check)" with the same
   question; compare `elapsed_seconds` in the gateway routing panel (the
   second call should be markedly faster once Redis has cached the
   completion).
3. **PII detection** -- use the demo question with a fake mobile number;
   Presidio masks it before it reaches the model (visible in the LiteLLM
   proxy logs / the gateway-level Langfuse trace).
4. **Guardrailing** -- use the "Ignore previous instructions..." demo
   question; `gates-keyword-guardrail` blocks it at the gateway (compare
   with the original SQL Agent tab, which blocks the same prompt at the app
   level via `gates_ai_common.input_validation` instead).
5. **Memory: budget** -- `curl "http://localhost:4000/key/info?key=<key>" -H "Authorization: Bearer $LITELLM_MASTER_KEY"`
   before/after a few calls; spend accumulates and survives
   `docker compose -f litellm/docker-compose.yml restart litellm-proxy`
   (Postgres-backed).
6. **Memory: conversation** -- ask a question, then a follow-up like "now
   just Region V"; `SQLAgentLiteLLM.run()` folds the prior turn into the
   next prompt (see the "Conversation memory" panel in the Streamlit page).

## Known mock-mode limitation (no proxy, no OPENAI_API_KEY)

With neither the LiteLLM proxy nor a live `OPENAI_API_KEY` configured, this
agent falls back to `agents.sql_agent.MockLLM`, which never emits a tool
call. LangChain's tool-calling SQL agent then treats the mock's raw SQL text
as an immediate final answer instead of executing it against the database,
so the evaluation stage (which scores the *executed* SQL) will show
`failed_evaluation`. This isn't a bug introduced by this demo -- it's
inherent to pairing a non-tool-calling mock model with `create_sql_agent`,
and the same underlying `MockLLM._generate()` return-type bug also crashes
`agents/sql_agent.py` itself if you ever run it with `OPENAI_API_KEY`
unset (try `OPENAI_API_KEY= python -m agents.sql_agent "..."` to see it).
It's left untouched there per your instruction not to modify the existing
agent; this new file works around it locally (see `_MockLLM` in
`agents/sql_agent_litellm.py`) just enough to avoid crashing.

None of this matters once the real proxy is running: with a live OpenAI (or
Gemini fallback) deployment behind `gates-sql-writer`, the model does emit
proper tool calls, the SQL actually executes, and evaluation passes -- same
as `agents/sql_agent.py` already does today with its configured
`OPENAI_API_KEY`. The demo script below assumes the real stack is up.

## Notes / things to verify against your installed LiteLLM image

- The image is pinned to `ghcr.io/berriai/litellm:1.99.1` in
  `docker-compose.yml` -- deliberately not `:main-stable` or `:latest`.
  LiteLLM discourages those rolling tags in production (a compromised CI
  dependency shipped tainted images under them in 2026), and `main-stable`
  specifically was slated to stop being published around September 2026.
  Bump the pinned version deliberately from
  [the releases page](https://github.com/BerriAI/litellm/releases) rather
  than switching back to a rolling tag.

LiteLLM's proxy config surface and plugin interfaces evolve between
releases; these were written against the documented interface at the time
of writing and should be spot-checked once the stack is actually running:

- The `resolved_model` field in the agent's stage trace reads
  `response.llm_output["model_name"]`, which LangChain populates from the
  model name in LiteLLM's completion response body -- confirm it reflects
  the underlying deployment (`gpt-4o-mini` vs `gemini-2.0-flash`) rather
  than the `gates-sql-writer` alias.
- `CustomGuardrail` hook method names/signatures in
  `litellm/guardrails/gates_keyword_guardrail.py`
  (`async_pre_call_hook`, `async_post_call_success_hook`).
- The `guardrail: guardrails.gates_keyword_guardrail.guardrail_gates_keyword`
  dotted-path loading convention in `litellm/config.yaml`.
- The exact Gemini model string for your `GEMINI_API_KEY`'s source --
  `gemini/gemini-2.0-flash` assumes a Google AI Studio key; a Vertex AI
  service-account key would instead need a `vertex_ai/...` prefix.
- The `mock_testing_fallbacks` request flag used to deterministically
  exercise the fallback path without actually breaking the primary key.
