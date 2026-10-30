const inr = new Intl.NumberFormat("en-IN");

export const rupees = (value: unknown): string => (typeof value === "number" ? `₹${inr.format(value)}` : String(value));

export interface FieldSpec {
  key: string;
  label: string;
  format: (value: unknown) => string;
}

export const FIELDS: FieldSpec[] = [
  { key: "payments_per_year", label: "Payments per year", format: String },
  { key: "installment_amount_inr", label: "Each installment", format: rupees },
  { key: "total_premium_over_paying_term_inr", label: "Total premium over paying term", format: rupees },
  { key: "next_due_date", label: "Next due date", format: String },
  { key: "grace_period_days", label: "Grace period (days)", format: String },
];

export const show = (spec: FieldSpec, value: unknown): string => (value === null || value === undefined || value === "" ? "no answer" : spec.format(value));
