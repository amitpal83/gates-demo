import type { CompareResponse, OntologyGraph, Policy } from "./types";

async function failure(response: Response): Promise<Error> {
  try {
    const body = await response.json();
    return new Error(typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail));
  } catch {
    return new Error(`${response.status} ${response.statusText}`);
  }
}

async function get<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) throw await failure(response);
  return response.json() as Promise<T>;
}

export const api = {
  policies: () => get<Policy[]>("/api/policies"),
  questions: () => get<string[]>("/api/questions"),
  ontology: () => get<OntologyGraph>("/api/ontology"),
  async compare(policy_number: string, question: string): Promise<CompareResponse> {
    const response = await fetch("/api/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ policy_number, question }),
    });
    if (!response.ok) throw await failure(response);
    return response.json() as Promise<CompareResponse>;
  },
};
