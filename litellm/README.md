# LiteLLM Proxy demo (SQL Agent LiteLLM)

This stack backs `agents/sql_agent_litellm.py` and the "SQL Agent LiteLLM"
page in the Streamlit app (`pages/1_SQL_Agent_LiteLLM.py`). It's the same
SQL-writing agent as `agents/sql_agent.py`, but routed through a LiteLLM
Proxy instead of calling OpenAI directly and doesnt use gates_ai_common
This falls back to the same offline `MockLLM` the original SQL agent uses.

## Running on an Ubuntu EC2 instance

This is written for the case where the repo + Python venv are already on
the box and only the LiteLLM stack is left to set up. 

All container ports in `litellm/docker-compose.yml` are bound to `127.0.0.1` only, so the app
(running outside Docker, in your existing venv) talks to the proxy at
`http://localhost:4000` exactly as it would locally 


**Instance size** -- Presidio's analyzer image bundles an NLP model and is
not lightweight; running LiteLLM + Postgres + Redis + both Presidio
containers + your Streamlit app on one box wants at least a `t3.medium`
(2 vCPU / 4 GB RAM)

### 1. Install Docker & Docker-compise
  

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
- `LITELLM_MASTER_KEY` -- one of the random strings above. Safe to - `POSTGRES_PASSWORD` -- the other random string. 

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


### 4. Create a virtual key


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
OpenAI model in the printed stage trace 

### 7. Run Streamlit persistently

    streamlit run streamlit_app.py --server.address 0.0.0.0 --server.port 8501
  
