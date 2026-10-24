import type { PriorityParts } from "../types";

const isFiniteNumber = (value: number) => Number.isFinite(value);

export function allowedPerUnit(ceiling: number, gstPercent: number): number | null {
  if (!isFiniteNumber(ceiling) || !isFiniteNumber(gstPercent) || ceiling < 0 || gstPercent < 0) {
    return null;
  }
  return ceiling * (1 + gstPercent / 100);
}

export function observedPerUnit(mrp: number, units: number | null): number | null {
  if (!isFiniteNumber(mrp) || mrp < 0 || units === null || !isFiniteNumber(units) || units <= 0) {
    return null;
  }
  return mrp / units;
}

export function discrepancyPercent(observed: number | null, allowed: number | null): number | null {
  if (observed === null || allowed === null || !isFiniteNumber(observed) || !isFiniteNumber(allowed) || allowed <= 0) {
    return null;
  }
  return ((observed - allowed) / allowed) * 100;
}

export function priorityScore(parts: PriorityParts): number {
  const values = [parts.discrepancy, parts.confidence, parts.evidence, parts.recurrence];
  if (values.some((value) => !isFiniteNumber(value))) return 0;
  return Math.min(100, Math.max(0, values.reduce((total, value) => total + value, 0)));
}

export function isPotentialDiscrepancy(
  observed: number | null,
  allowed: number | null,
  tolerancePercent = 1,
): boolean {
  if (!isFiniteNumber(tolerancePercent) || tolerancePercent < 0) return false;
  const difference = discrepancyPercent(observed, allowed);
  return difference !== null && difference > tolerancePercent;
}

export function roundForDisplay(value: number, decimals: number): number {
  const factor = 10 ** decimals;
  return Math.round((value + Number.EPSILON) * factor) / factor;
}

export function formatNumber(value: number | null, decimals = 2): string {
  return value === null ? "—" : roundForDisplay(value, decimals).toFixed(decimals);
}

export function formatCurrency(value: number | null, decimals = 2): string {
  return value === null ? "—" : `₹${formatNumber(value, decimals)}`;
}

export function formatPercent(value: number | null, decimals = 2, signed = true): string {
  if (value === null) return "—";
  const rounded = formatNumber(value, decimals);
  return `${signed && value > 0 ? "+" : ""}${rounded}%`;
}

export interface CalculationView {
  allowed: number | null;
  observed: number | null;
  discrepancy: number | null;
  allowedFormula: string;
  observedFormula: string;
  discrepancyFormula: string;
}

export function calculationView(
  ceiling: number,
  gstPercent: number,
  mrp: number,
  units: number | null,
): CalculationView {
  const allowed = allowedPerUnit(ceiling, gstPercent);
  const observed = observedPerUnit(mrp, units);
  const discrepancy = discrepancyPercent(observed, allowed);

  const allowedFormula = allowed === null
    ? "Allowed per unit unavailable"
    : `${formatCurrency(ceiling, 4)} × (1 + ${formatNumber(gstPercent, 2)} ÷ 100) = ${formatCurrency(allowed, 4)}`;

  const observedFormula = observed === null || units === null
    ? "Observed per unit unavailable: a positive integer pack count is required"
    : `${formatCurrency(mrp, 2)} ÷ ${formatNumber(units, 0)} units = ${formatCurrency(observed, 4)}`;

  const discrepancyFormula = discrepancy === null || units === null
    ? "Potential difference unavailable until observed and allowed prices are valid"
    : `(((${formatCurrency(mrp, 2)} ÷ ${formatNumber(units, 0)}) − (${formatCurrency(ceiling, 4)} × (1 + ${formatNumber(gstPercent, 2)} ÷ 100))) ÷ (${formatCurrency(ceiling, 4)} × (1 + ${formatNumber(gstPercent, 2)} ÷ 100))) × 100 = ${formatPercent(discrepancy)}`;

  return { allowed, observed, discrepancy, allowedFormula, observedFormula, discrepancyFormula };
}

export function priorityFormula(parts: PriorityParts): string {
  return `${formatNumber(parts.discrepancy, 0)} discrepancy + ${formatNumber(parts.confidence, 0)} confidence + ${formatNumber(parts.evidence, 0)} evidence + ${formatNumber(parts.recurrence, 0)} recurrence = ${formatNumber(priorityScore(parts), 0)}`;
}
