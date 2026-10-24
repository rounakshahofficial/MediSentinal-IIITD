import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";
import { AlertCircle, FlaskConical, HelpCircle, Inbox, LoaderCircle, RefreshCw, RotateCcw } from "lucide-react";
import type { CaseStatus } from "../types";
import { formatNumber } from "../lib/calc";

export const cx = (...classes: Array<string | false | null | undefined>) => classes.filter(Boolean).join(" ");

export function FocusButton({ children, className, ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={cx(
        "inline-flex min-h-10 items-center justify-center gap-2 rounded-lg px-4 text-sm font-semibold transition duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 active:translate-y-px",
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}

export function Card({ children, className = "", ...props }: { children: ReactNode; className?: string } & HTMLAttributes<HTMLElement>) {
  return <section className={cx("rounded-2xl border border-slate-200 bg-white shadow-sm", className)} {...props}>{children}</section>;
}

export function DemoBadge() {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-800">
      <FlaskConical className="h-3.5 w-3.5" aria-hidden="true" />Demo data
    </span>
  );
}

const STATUS_LABELS: Record<CaseStatus, string> = {
  potential_discrepancy: "Potential discrepancy",
  needs_verification: "Needs verification",
  confirmed_for_review: "Confirmed for review",
  dismissed: "Dismissed",
  needs_more_evidence: "Need more evidence",
};

export function statusLabel(status: CaseStatus): string {
  return STATUS_LABELS[status];
}

export function StatusChip({ status }: { status: CaseStatus }) {
  const tone = status === "potential_discrepancy"
    ? "border-red-200 bg-red-50 text-red-800"
    : status === "needs_verification" || status === "needs_more_evidence"
      ? "border-amber-200 bg-amber-50 text-amber-900"
      : status === "confirmed_for_review"
        ? "border-green-200 bg-green-50 text-green-800"
        : "border-slate-200 bg-slate-100 text-slate-700";
  return <span className={cx("inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold", tone)}>{statusLabel(status)}</span>;
}

export function ConfidenceBadge({ value }: { value: number }) {
  const tone = value >= 95
    ? "border-green-200 bg-green-50 text-green-800"
    : value >= 80
      ? "border-amber-200 bg-amber-50 text-amber-900"
      : "border-red-200 bg-red-50 text-red-800";
  return <span className={cx("rounded-full border px-2 py-0.5 text-[11px] font-bold tabular-nums", tone)} title={`${formatNumber(value, 0)} correct characters out of 100 estimated`}>{formatNumber(value, 0)}% confidence</span>;
}

export function PriorityHelp({ formula }: { formula: string }) {
  return (
    <span className="group relative inline-flex">
      <button type="button" className="rounded-full text-slate-400 hover:text-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600" aria-label="Why this priority score"><HelpCircle className="h-4 w-4" /></button>
      <span role="tooltip" className="pointer-events-none absolute bottom-full right-0 z-20 mb-2 hidden w-64 rounded-lg bg-slate-950 p-3 font-mono text-[11px] leading-5 text-white shadow-lg group-hover:block group-focus-within:block">{formula}</span>
    </span>
  );
}

export function LoadingState() {
  return (
    <Card className="flex min-h-72 flex-col items-center justify-center p-8 text-center" aria-live="polite" aria-busy="true">
      <LoaderCircle className="h-8 w-8 animate-spin text-blue-600" aria-hidden="true" />
      <h2 className="mt-4 text-base font-semibold text-slate-900">Loading demo records</h2>
      <p className="mt-1 max-w-sm text-sm text-slate-600">Preparing reviewer-safe mock data for this screen.</p>
    </Card>
  );
}

export function EmptyState({ onReset }: { onReset: () => void }) {
  return (
    <Card className="flex min-h-72 flex-col items-center justify-center border-dashed p-8 text-center">
      <span className="grid h-12 w-12 place-items-center rounded-full bg-slate-100 text-slate-500"><Inbox className="h-5 w-5" /></span>
      <h2 className="mt-4 text-base font-semibold">No demo records in this view</h2>
      <p className="mt-1 max-w-sm text-sm text-slate-600">Clear filters or restore the ready state to continue.</p>
      <FocusButton onClick={onReset} className="mt-5 border border-slate-300 bg-white text-slate-800 hover:bg-slate-50"><RotateCcw className="h-4 w-4" />Restore demo data</FocusButton>
    </Card>
  );
}

export function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <Card className="flex min-h-72 flex-col items-center justify-center border-red-200 p-8 text-center" role="alert">
      <span className="grid h-12 w-12 place-items-center rounded-full bg-red-50 text-red-700"><AlertCircle className="h-5 w-5" /></span>
      <h2 className="mt-4 text-base font-semibold">Could not load this demo view</h2>
      <p className="mt-1 max-w-sm text-sm text-slate-600">Nothing was changed. Retry to restore mock data.</p>
      <FocusButton onClick={onRetry} className="mt-5 bg-blue-600 text-white hover:bg-blue-700"><RefreshCw className="h-4 w-4" />Retry</FocusButton>
    </Card>
  );
}
