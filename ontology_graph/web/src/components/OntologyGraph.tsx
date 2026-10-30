import { useMemo } from "react";
import { Background, Controls, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { OntologyGraph as Graph, OntologyNode, Policy } from "../types";

// Which attributes each class shows on its card, in order.
const CARD_PROPS: Record<string, string[]> = {
  Plan: ["uin", "planNumber", "premiumPayingTermsYears", "policyTermsYears"],
  PremiumMode: ["modeCode", "installmentsPerYear", "intervalMonths", "minInstallmentInr"],
  GracePeriod: ["days"],
  LockInPeriod: ["durationYears"],
  Benefit: ["payoutMode", "minPctOfPremiumsPaid"],
  Insurer: [],
};

const ROW_GAP = 130;
const POLICY_NODE = "__policy__";

interface CardData extends Record<string, unknown> {
  cls: string;
  label: string;
  rows: [string, string][];
  highlight?: boolean;
  policy?: boolean;
}

// Eight handles per card (a source and a target on each side) so each edge can leave and enter on the side that faces its other end.
const SIDES: [string, Position][] = [
  ["right", Position.Right],
  ["left", Position.Left],
  ["top", Position.Top],
  ["bottom", Position.Bottom],
];

function Card({ data }: NodeProps<Node<CardData>>) {
  return (
    <div className={`ont-card cls-${data.cls}${data.highlight ? " is-highlight" : ""}${data.policy ? " is-policy" : ""}`}>
      {SIDES.map(([side, position]) => (
        <span key={side}>
          <Handle id={`s-${side}`} type="source" position={position} className="ont-handle" />
          <Handle id={`t-${side}`} type="target" position={position} className="ont-handle" />
        </span>
      ))}
      <div className="ont-class">{data.policy ? "Customer policy (PostgreSQL)" : data.cls}</div>
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
      {data.highlight && <div className="ont-badge">used by this policy</div>}
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
  return (CARD_PROPS[node.class] ?? []).filter((key) => node.props[key] !== undefined).map((key) => [key, node.props[key]]);
}

function layout(graph: Graph, policy: Policy | undefined): { nodes: Node<CardData>[]; edges: Edge[] } {
  const byClass = (cls: string) => graph.nodes.filter((n) => n.class === cls);
  const modes = byClass("PremiumMode").sort((a, b) => Number(a.props.installmentsPerYear) - Number(b.props.installmentsPerYear));
  const modeY = new Map(modes.map((m, i) => [m.id, i * ROW_GAP]));
  const midY = modes.length ? ((modes.length - 1) * ROW_GAP) / 2 : 0;

  const position = new Map<string, { x: number; y: number }>();
  modes.forEach((m) => position.set(m.id, { x: 700, y: modeY.get(m.id)! }));
  byClass("Plan").forEach((n) => position.set(n.id, { x: 340, y: midY }));
  byClass("Insurer").forEach((n) => position.set(n.id, { x: 0, y: midY }));
  byClass("LockInPeriod").forEach((n) => position.set(n.id, { x: 340, y: midY - 1.6 * ROW_GAP }));
  byClass("Benefit").forEach((n) => position.set(n.id, { x: 340, y: midY + 1.6 * ROW_GAP }));
  byClass("GracePeriod").forEach((n) => {
    const ys = graph.edges.filter((e) => e.label === "hasGracePeriod" && e.target === n.id).map((e) => modeY.get(e.source) ?? 0);
    position.set(n.id, { x: 1060, y: ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : 0 });
  });
  graph.nodes.forEach((n, i) => {
    if (!position.has(n.id)) position.set(n.id, { x: 1060, y: 160 * i });
  });

  const used = policy ? modes.find((m) => Number(m.props.modeCode) === policy.mode_code) : undefined;
  const nodes: Node<CardData>[] = graph.nodes.map((n) => ({
    id: n.id,
    type: "card",
    position: position.get(n.id)!,
    data: { cls: n.class, label: n.label, rows: rowsFor(n), highlight: n.id === used?.id },
    draggable: true,
  }));

  const edges: Edge[] = graph.edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    label: e.label,
    type: "smoothstep",
    markerEnd: { type: MarkerType.ArrowClosed },
    ...handles(position.get(e.source) ?? { x: 0, y: 0 }, position.get(e.target) ?? { x: 0, y: 0 }),
  }));

  if (policy && used) {
    const policyPos = { x: 700, y: modes.length * ROW_GAP + 10 };
    nodes.push({
      id: POLICY_NODE,
      type: "card",
      position: policyPos,
      data: {
        cls: "Policy",
        label: `${policy.policy_number} · ${policy.full_name}`,
        rows: [["mode_code", String(policy.mode_code)], ["plan_uin", policy.plan_uin]],
        policy: true,
      },
    });
    edges.push({
      id: "policy-join",
      source: POLICY_NODE,
      target: used.id,
      label: `joins on mode_code = ${policy.mode_code}`,
      type: "smoothstep",
      animated: true,
      className: "join-edge",
      markerEnd: { type: MarkerType.ArrowClosed },
      sourceHandle: "s-top",
      targetHandle: "t-bottom",
    });
  }
  return { nodes, edges };
}

export default function OntologyGraph({ graph, policy }: { graph: Graph | null; policy: Policy | undefined }) {
  const { nodes, edges } = useMemo(() => (graph ? layout(graph, policy) : { nodes: [], edges: [] }), [graph, policy]);
  if (!graph) return <div className="empty">Loading the plan ontology…</div>;
  if (graph.nodes.length === 0) return <div className="empty">No ontology yet. Upload the plan PDF to the licdocuments bucket and let the pipeline finish.</div>;
  return (
    <div className="graph-frame" role="img" aria-label="Plan ontology graph">
      <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.12 }} minZoom={0.3} maxZoom={1.5} nodesConnectable={false} proOptions={{ hideAttribution: true }}>
        <Background gap={20} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
