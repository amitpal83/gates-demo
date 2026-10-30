export interface Policy {
  policy_number: string;
  full_name: string;
  city: string;
  plan_uin: string;
  plan_name: string;
  mode_code: number;
  installment_premium: number;
  premium_paying_term_years: number;
  policy_term_years: number;
  basic_sum_assured: number;
  start_date: string;
  last_paid_date: string;
  status: string;
}

export interface OntologyNode {
  id: string;
  label: string;
  class: string;
  props: Record<string, string>;
}

export interface OntologyEdge {
  id: string;
  source: string;
  target: string;
  label: string;
}

export interface OntologyGraph {
  nodes: OntologyNode[];
  edges: OntologyEdge[];
}

export type Verdict = "correct" | "wrong" | "unanswered";

export interface Check {
  truth: string | number;
  answer: string | number | null;
  verdict: Verdict;
}

export interface AgentResult {
  status: string;
  answer: Record<string, string | number | null>;
  prompt: string;
  ontology_facts?: string[];
  checks: Record<string, Check>;
  summary: Record<Verdict, number>;
}

export type AgentKey = "ontology" | "sql";

export interface AskResponse {
  policy_number: string;
  question: string;
  truth: Record<string, string | number>;
  agent: AgentKey;
  result: AgentResult;
}

export interface CompareResponse {
  policy_number: string;
  question: string;
  truth: Record<string, string | number>;
  ontology_agent: AgentResult;
  sql_agent: AgentResult;
}
