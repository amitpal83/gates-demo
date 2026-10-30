import type { AgentResult, Verdict } from "../types";
import { FIELDS, show } from "../format";

const VERDICT_TEXT: Record<Verdict, string> = { correct: "✓ Correct", wrong: "✗ Wrong", unanswered: "– No answer" };

interface Props {
  title: string;
  subtitle: string;
  tone: "ontology" | "sql";
  result: AgentResult;
}

export default function AgentPanel({ title, subtitle, tone, result }: Props) {
  const { correct, wrong, unanswered } = result.summary;
  return (
    <section className={`panel agent tone-${tone}`}>
      <header>
        <h3>{title}</h3>
        <p className="muted">{subtitle}</p>
        <p className="score">
          <strong>{correct}</strong> correct · <strong>{wrong}</strong> wrong · <strong>{unanswered}</strong> no answer
        </p>
      </header>

      {result.status !== "ok" && <p className="error">Agent status: {result.status}</p>}
      <blockquote>{String(result.answer.answer ?? "(no explanation returned)")}</blockquote>

      <table>
        <thead>
          <tr>
            <th>Field</th>
            <th>Agent said</th>
            <th>Correct value</th>
            <th>Result</th>
          </tr>
        </thead>
        <tbody>
          {FIELDS.map((spec) => {
            const check = result.checks[spec.key];
            return (
              <tr key={spec.key} className={`row-${check.verdict}`}>
                <td>{spec.label}</td>
                <td>{show(spec, check.answer)}</td>
                <td>{show(spec, check.truth)}</td>
                <td>
                  <span className={`chip chip-${check.verdict}`}>{VERDICT_TEXT[check.verdict]}</span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {result.ontology_facts && (
        <details>
          <summary>Ontology facts this agent was given ({result.ontology_facts.length})</summary>
          <pre>{result.ontology_facts.join("\n") || "(none)"}</pre>
        </details>
      )}
      <details>
        <summary>Exact prompt sent to the model</summary>
        <pre>{result.prompt}</pre>
      </details>
    </section>
  );
}
