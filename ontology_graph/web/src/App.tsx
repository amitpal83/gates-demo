import { useEffect, useState } from "react";
import { api } from "./api";
import { rupees } from "./format";
import type { CompareResponse, OntologyGraph as Graph, Policy } from "./types";
import AgentPanel from "./components/AgentPanel";
import Charts from "./components/Charts";
import OntologyGraph from "./components/OntologyGraph";

export default function App() {
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [questions, setQuestions] = useState<string[]>([]);
  const [graph, setGraph] = useState<Graph | null>(null);
  const [selected, setSelected] = useState<string>("");
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<CompareResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [graphError, setGraphError] = useState<string | null>(null);

  useEffect(() => {
    api.policies().then((p) => { setPolicies(p); if (p.length) setSelected(p[0].policy_number); }).catch((e: Error) => setError(e.message));
    api.questions().then((q) => { setQuestions(q); if (q.length) setQuestion(q[0]); }).catch((e: Error) => setError(e.message));
    api.ontology().then(setGraph).catch((e: Error) => { setGraphError(e.message); setGraph({ nodes: [], edges: [] }); });
  }, []);

  const policy = policies.find((p) => p.policy_number === selected);

  async function ask() {
    if (!selected || !question.trim()) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await api.compare(selected, question.trim()));
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
        <p className="muted">
          LIC’s Protection Plus. The same question goes to two agents with the same model and the same customer record. Only one of them also gets the plan ontology.
        </p>
      </header>

      <section className="panel">
        <h2>1. Customer policies as the database stores them</h2>
        <p className="muted">The database keeps only a code in <code>mode_code</code>. What the code means is not stored in SQL.</p>
        <div className="policies" role="radiogroup" aria-label="Choose a policy">
          {policies.map((p) => (
            <button key={p.policy_number} role="radio" aria-checked={p.policy_number === selected} className={`policy${p.policy_number === selected ? " is-selected" : ""}`} onClick={() => { setSelected(p.policy_number); setResult(null); }}>
              <span className="policy-id">{p.policy_number}</span>
              <span className="policy-name">{p.full_name}</span>
              <span className="policy-meta">{rupees(p.installment_premium)} per installment · paying term {p.premium_paying_term_years} yrs</span>
              <span className="mode-pill">mode_code = {p.mode_code}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="panel">
        <h2>2. The plan ontology built from the brochure</h2>
        <p className="muted">Extracted from the plan PDF by the pipeline and stored in GraphDB. The highlighted mode is the one this policy’s code points to.</p>
        {graphError && <p className="error">{graphError}</p>}
        <OntologyGraph graph={graph} policy={policy} />
      </section>

      <section className="panel">
        <h2>3. Ask both agents the same question</h2>
        <div className="chips">
          {questions.map((q) => (
            <button key={q} className={`chip-btn${q === question ? " is-active" : ""}`} onClick={() => setQuestion(q)}>{q}</button>
          ))}
        </div>
        <div className="ask">
          <input value={question} onChange={(e) => setQuestion(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") ask(); }} placeholder="Ask about this policy’s premiums" maxLength={500} aria-label="Question" />
          <button className="primary" onClick={ask} disabled={busy || !selected || !question.trim()}>{busy ? "Asking both agents…" : "Ask both agents"}</button>
        </div>
        {error && <p className="error" role="alert">{error}</p>}
      </section>

      {result && (
        <>
          <section className="panel">
            <h2>Results for {result.policy_number}</h2>
            <p className="muted">
              Correct answer: {String(result.truth.mode_label)} premium, {String(result.truth.payments_per_year)} payment(s) a year, next due {String(result.truth.next_due_date)}.
            </p>
            <Charts result={result} />
          </section>
          <div className="agents">
            <AgentPanel title="Agent A · Ontology + PostgreSQL" subtitle="Policy record and the plan facts from GraphDB" tone="ontology" result={result.ontology_agent} />
            <AgentPanel title="Agent B · PostgreSQL only" subtitle="Policy record and column descriptions only" tone="sql" result={result.sql_agent} />
          </div>
        </>
      )}
    </main>
  );
}
