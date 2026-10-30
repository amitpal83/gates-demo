import { useEffect, useState } from "react";
import { api } from "./api";
import type { AgentKey, AskResponse, CompareResponse, OntologyGraph as Graph, Policy } from "./types";
import AgentPanel from "./components/AgentPanel";
import Charts from "./components/Charts";
import OntologyModal from "./components/OntologyModal";

type Mode = AgentKey | "compare";

const AGENTS: Record<AgentKey, { title: string; subtitle: string }> = {
  ontology: { title: "Agent A · Ontology + PostgreSQL", subtitle: "Policy record and the plan facts from GraphDB" },
  sql: { title: "Agent B · PostgreSQL only", subtitle: "Policy record and column descriptions only" },
};

const MODES: { key: Mode; label: string }[] = [
  { key: "ontology", label: "Ontology + PostgreSQL agent" },
  { key: "sql", label: "PostgreSQL-only agent" },
  { key: "compare", label: "Compare both" },
];

type View = { kind: "single"; data: AskResponse } | { kind: "compare"; data: CompareResponse };

export default function App() {
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [questions, setQuestions] = useState<string[]>([]);
  const [graph, setGraph] = useState<Graph | null>(null);
  const [selected, setSelected] = useState("");
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState<Mode>("ontology");
  const [view, setView] = useState<View | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ontologyOpen, setOntologyOpen] = useState(false);

  useEffect(() => {
    api.policies().then((p) => { setPolicies(p); if (p.length) setSelected(p[0].policy_number); }).catch((e: Error) => setError(e.message));
    api.questions().then((q) => { setQuestions(q); if (q.length) setQuestion(q[0]); }).catch((e: Error) => setError(e.message));
  }, []);

  function openOntology() {
    setOntologyOpen(true);
    if (!graph) api.ontology().then(setGraph).catch((e: Error) => { setError(e.message); setGraph({ nodes: [], edges: [] }); });
  }

  const askLabel = mode === "compare" ? "Ask both and compare" : `Ask the ${MODES.find((m) => m.key === mode)!.label}`;

  async function ask() {
    if (!selected || !question.trim()) return;
    setBusy(true);
    setError(null);
    try {
      if (mode === "compare") setView({ kind: "compare", data: await api.compare(selected, question.trim()) });
      else setView({ kind: "single", data: await api.ask(selected, question.trim(), mode) });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <header className="top">
        <h1>Ontology layer vs SQL layer</h1>
        <button className="secondary" onClick={openOntology}>Open ontology</button>
      </header>

      <section className="panel">
        <div className="controls">
          <label className="field">
            <span>Policy</span>
            <select value={selected} onChange={(e) => { setSelected(e.target.value); setView(null); }}>
              {policies.map((p) => (
                <option key={p.policy_number} value={p.policy_number}>{p.policy_number} · {p.full_name}</option>
              ))}
            </select>
          </label>

          <div className="field">
            <span id="agent-label">Ask</span>
            <div className="seg" role="radiogroup" aria-labelledby="agent-label">
              {MODES.map((m) => (
                <button key={m.key} role="radio" aria-checked={m.key === mode} className={m.key === mode ? "is-active" : ""} onClick={() => { setMode(m.key); setView(null); setError(null); }}>
                  {m.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="chips">
          {questions.map((q) => (
            <button key={q} className={`chip-btn${q === question ? " is-active" : ""}`} onClick={() => setQuestion(q)}>{q}</button>
          ))}
        </div>
        <div className="ask">
          <input value={question} onChange={(e) => setQuestion(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") ask(); }} placeholder="Ask about this policy’s premiums" maxLength={500} aria-label="Question" />
          <button className="primary" onClick={ask} disabled={busy || !selected || !question.trim()}>{busy ? "Asking…" : askLabel}</button>
        </div>
        {error && <p className="error" role="alert">{error}</p>}
      </section>

      {view?.kind === "single" && (
        <AgentPanel title={AGENTS[view.data.agent].title} subtitle={AGENTS[view.data.agent].subtitle} tone={view.data.agent} result={view.data.result} />
      )}

      {view?.kind === "compare" && (
        <>
          <section className="panel">
            <h2>Comparison for {view.data.policy_number}</h2>
            <Charts result={view.data} />
          </section>
          <div className="agents">
            <AgentPanel title={AGENTS.ontology.title} subtitle={AGENTS.ontology.subtitle} tone="ontology" result={view.data.ontology_agent} />
            <AgentPanel title={AGENTS.sql.title} subtitle={AGENTS.sql.subtitle} tone="sql" result={view.data.sql_agent} />
          </div>
        </>
      )}

      <OntologyModal open={ontologyOpen} onClose={() => setOntologyOpen(false)} graph={graph} />
    </main>
  );
}
