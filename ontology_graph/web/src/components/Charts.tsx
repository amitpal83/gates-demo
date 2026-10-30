import { Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer, XAxis, YAxis } from "recharts";
import type { CompareResponse } from "../types";

const SERIES = [
  { name: "Correct value", color: "var(--series-truth)" },
  { name: "Ontology agent", color: "var(--series-ontology)" },
  { name: "SQL-only agent", color: "var(--series-sql)" },
];

interface Metric {
  title: string;
  key: string;
  scale: number;
  unit: string;
}

const METRICS: Metric[] = [
  { title: "Payments per year", key: "payments_per_year", scale: 1, unit: "" },
  { title: "Total premium over paying term (₹ lakh)", key: "total_premium_over_paying_term_inr", scale: 100000, unit: "L" },
];

function MetricChart({ metric, result }: { metric: Metric; result: CompareResponse }) {
  const values = [result.ontology_agent.checks[metric.key].truth, result.ontology_agent.checks[metric.key].answer, result.sql_agent.checks[metric.key].answer];
  const data = SERIES.map((s, i) => {
    const raw = values[i];
    const number = typeof raw === "number" ? raw / metric.scale : null;
    return { name: s.name, value: number ?? 0, label: number === null ? "no answer" : `${Math.round(number * 100) / 100}${metric.unit}`, color: s.color };
  });
  return (
    <figure className="chart">
      <figcaption>{metric.title}</figcaption>
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={data} margin={{ top: 22, right: 8, left: 0, bottom: 4 }}>
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis dataKey="name" tick={{ fill: "var(--muted)", fontSize: 12 }} axisLine={false} tickLine={false} />
          <YAxis tick={{ fill: "var(--muted)", fontSize: 12 }} axisLine={false} tickLine={false} width={36} />
          <Bar dataKey="value" radius={[4, 4, 0, 0]} maxBarSize={64}>
            {data.map((d) => (
              <Cell key={d.name} fill={d.color} />
            ))}
            <LabelList dataKey="label" position="top" fill="var(--text)" fontSize={12} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </figure>
  );
}

export default function Charts({ result }: { result: CompareResponse }) {
  return (
    <div className="charts">
      {METRICS.map((m) => (
        <MetricChart key={m.key} metric={m} result={result} />
      ))}
    </div>
  );
}
