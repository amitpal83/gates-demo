import { useMemo } from "react";
import { Background, Controls, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { OntologyGraph as Graph, OntologyNode } from "../types";

const CLASS_LABEL: Record<string, string> = {
  Insurer: "Insurer",
  Plan: "Plan",
  PremiumMode: "Premium mode",
  GracePeriod: "Grace period",
  LockInPeriod: "Lock-in period",
  Benefit: "Benefit",
};

const EDGE_LABEL: Record<string, string> = {
  issuedBy: "issued by",
  acceptsMode: "accepts",
  hasGracePeriod: "grace period",
  hasLockIn: "lock-in",
  hasBenefit: "pays",
};

const num = (v: string) => String(Number(v));
interface PropSpec { key: string; label: string; format: (v: string) => string }

// Which attributes each class shows on its card, with readable labels.
const PROPS: Record<string, PropSpec[]> = {
  Insurer: [],
  Plan: [
    { key: "uin", label: "UIN", format: (v) => v },
    { key: "planNumber", label: "Plan no.", format: num },
    { key: "premiumPayingTermsYears", label: "Paying terms", format: (v) => `${v} yrs` },
    { key: "policyTermsYears", label: "Policy terms", format: (v) => `${v} yrs` },
  ],
  PremiumMode: [
    { key: "installmentsPerYear", label: "Installments / year", format: num },
    { key: "intervalMonths", label: "Every", format: (v) => `${num(v)} month${num(v) === "1" ? "" : "s"}` },
  ],
  GracePeriod: [{ key: "days", label: "Time to pay", format: (v) => `${num(v)} days` }],
  LockInPeriod: [{ key: "durationYears", label: "Duration", format: (v) => `${num(v)} years` }],
  Benefit: [
    { key: "payoutMode", label: "Paid as", format: (v) => v },
    { key: "minPctOfPremiumsPaid", label: "At least", format: (v) => `${num(v)}% of premiums paid` },
  ],
};

const COLUMN = { insurer: 0, plan: 310, mode: 690, grace: 1050 };
const ROW_GAP = 190;

interface CardData extends Record<string, unknown> {
  cls: string;
  label: string;
  code?: string;
  rows: [string, string][];
}

// Eight handles per card (a source and a target on each side) so every edge can leave and enter on the side that faces its other end.
const SIDES: [string, Position][] = [
  ["right", Position.Right],
  ["left", Position.Left],
  ["top", Position.Top],
  ["bottom", Position.Bottom],
];

function Card({ data }: NodeProps<Node<CardData>>) {
  return (
    <div className={`ont-card cls-${data.cls}`}>
      {SIDES.map(([side, position]) => (
        <span key={side}>
          <Handle id={`s-${side}`} type="source" position={position} className="ont-handle" />
          <Handle id={`t-${side}`} type="target" position={position} className="ont-handle" />
        </span>
      ))}
      <div className="ont-head">
        <span className="ont-class">{CLASS_LABEL[data.cls] ?? data.cls}</span>
        {data.code && <span className="ont-code">{data.code}</span>}
      </div>
      <div className="ont-label">{data.label}</div>
      {data.rows.length > 0 && (
        <dl className="ont-rows">
          {data.rows.map(([key, value]) => (
            <div key={key}>
              <dt>{key}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

const nodeTypes = { card: Card };

function handles(from: { x: number; y: number }, to: { x: number; y: number }): { sourceHandle: string; targetHandle: string } {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  if (Math.abs(dx) >= Math.abs(dy)) return dx >= 0 ? { sourceHandle: "s-right", targetHandle: "t-left" } : { sourceHandle: "s-left", targetHandle: "t-right" };
  return dy >= 0 ? { sourceHandle: "s-bottom", targetHandle: "t-top" } : { sourceHandle: "s-top", targetHandle: "t-bottom" };
}

function rowsFor(node: OntologyNode): [string, string][] {
  return (PROPS[node.class] ?? []).filter((spec) => node.props[spec.key] !== undefined).map((spec) => [spec.label, spec.format(node.props[spec.key])]);
}

function layout(graph: Graph): { nodes: Node<CardData>[]; edges: Edge[] } {
  const byClass = (cls: string) => graph.nodes.filter((n) => n.class === cls);
  const modes = byClass("PremiumMode").sort((a, b) => Number(a.props.installmentsPerYear) - Number(b.props.installmentsPerYear));
  const modeY = new Map(modes.map((m, i) => [m.id, i * ROW_GAP]));
  const midY = modes.length ? ((modes.length - 1) * ROW_GAP) / 2 : 0;

  const position = new Map<string, { x: number; y: number }>();
  modes.forEach((m) => position.set(m.id, { x: COLUMN.mode, y: modeY.get(m.id)! }));
  byClass("Insurer").forEach((n) => position.set(n.id, { x: COLUMN.insurer, y: midY }));
  byClass("Plan").forEach((n) => position.set(n.id, { x: COLUMN.plan, y: midY }));
  byClass("LockInPeriod").forEach((n) => position.set(n.id, { x: COLUMN.plan, y: midY - 215 }));
  byClass("Benefit").forEach((n) => position.set(n.id, { x: COLUMN.plan, y: midY + 215 }));
  byClass("GracePeriod").forEach((n) => {
    const ys = graph.edges.filter((e) => e.label === "hasGracePeriod" && e.target === n.id).map((e) => modeY.get(e.source) ?? 0);
    position.set(n.id, { x: COLUMN.grace, y: ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : 0 });
  });
  graph.nodes.forEach((n, i) => {
    if (!position.has(n.id)) position.set(n.id, { x: COLUMN.grace, y: 190 * i });
  });

  const nodes: Node<CardData>[] = graph.nodes.map((n) => ({
    id: n.id,
    type: "card",
    position: position.get(n.id)!,
    data: {
      cls: n.class,
      label: n.label.replace(/\s*\(.*\)\s*$/, ""),
      code: n.class === "PremiumMode" && n.props.modeCode !== undefined ? `Code ${num(n.props.modeCode)}` : undefined,
      rows: rowsFor(n),
    },
  }));

  const edges: Edge[] = graph.edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    label: EDGE_LABEL[e.label] ?? e.label,
    type: "default",
    style: { stroke: "var(--muted)", strokeWidth: 1.5 },
    labelStyle: { fontSize: 12, fill: "var(--text)" },
    labelBgStyle: { fill: "var(--surface)", fillOpacity: 0.95 },
    labelBgPadding: [6, 3] as [number, number],
    labelBgBorderRadius: 6,
    ...handles(position.get(e.source) ?? { x: 0, y: 0 }, position.get(e.target) ?? { x: 0, y: 0 }),
  }));
  return { nodes, edges };
}

export default function OntologyGraph({ graph }: { graph: Graph | null }) {
  const { nodes, edges } = useMemo(() => (graph ? layout(graph) : { nodes: [], edges: [] }), [graph]);
  if (!graph) return <div className="empty">Loading the plan ontology…</div>;
  if (graph.nodes.length === 0) return <div className="empty">No ontology yet. Upload the plan PDF to the licdocuments bucket and let the pipeline finish.</div>;
  return (
    <div className="graph-frame" role="img" aria-label="Plan ontology graph">
      <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.1 }} minZoom={0.4} maxZoom={1.3} nodesConnectable={false} proOptions={{ hideAttribution: true }}>
        <Background gap={24} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
