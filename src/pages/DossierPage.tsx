import { CheckCircle2, Clock3, ExternalLink, ImagePlus, XCircle } from "lucide-react";
import type { Case, ReviewAction } from "../types";
import { calculationView, formatCurrency, formatPercent, observedPerUnit, priorityFormula, priorityScore } from "../lib/calc";
import { Card, DemoBadge, FocusButton, StatusChip } from "../components/ui";

interface DossierPageProps {
  selectedCase: Case;
  onReview: (action: ReviewAction) => Promise<void>;
}

export function DossierPage({ selectedCase, onReview }: DossierPageProps) {
  const { listing, reference } = selectedCase;
  const calc = calculationView(reference.ceilingPricePerUnit, reference.gstPercent, listing.mrp, listing.unitsInPack);
  const score = priorityScore(selectedCase.priorityParts);
  const steps = [
    { label: "Placeholder ceiling", value: `${formatCurrency(reference.ceilingPricePerUnit, 4)} / ${reference.unit}`, formula: `${reference.sourceOrder} → ${formatCurrency(reference.ceilingPricePerUnit, 4)} per ${reference.unit}` },
    { label: "Allowed with GST", value: `${formatCurrency(calc.allowed)} / ${reference.unit}`, formula: calc.allowedFormula },
    { label: "Observed per unit", value: `${formatCurrency(calc.observed)} / ${reference.unit}`, formula: calc.observedFormula },
    { label: "Potential difference", value: formatPercent(calc.discrepancy), formula: calc.discrepancyFormula },
  ];

  return (
    <div className="space-y-6">
      <Card className="p-5 sm:p-6"><div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between"><div><div className="flex flex-wrap items-center gap-2"><span className="font-mono text-xs font-bold text-slate-500">{selectedCase.id}</span><StatusChip status={selectedCase.status} />{selectedCase.isRecurrent && <span className="rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-800">Repeat ×{selectedCase.history.length}</span>}</div><h2 className="mt-3 text-xl font-bold">{listing.productName}</h2><p className="mt-1 text-sm text-slate-600">{listing.site} · Priority {score} / 100</p><p className="mt-1 font-mono text-[11px] text-slate-500">{priorityFormula(selectedCase.priorityParts)}</p></div><div className="rounded-xl bg-slate-50 p-4"><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Potential difference</p><p className="mt-1 text-2xl font-bold text-red-700">{formatPercent(calc.discrepancy)}</p><p className="mt-1 max-w-md font-mono text-[10px] text-slate-500">{calc.discrepancyFormula}</p></div></div></Card>

      <div className="grid gap-6 xl:grid-cols-[1fr_.95fr]">
        <div className="space-y-6">
          <Card className="p-4 sm:p-6"><div className="flex items-center justify-between gap-3"><h2 className="text-base font-semibold">Source evidence</h2><DemoBadge /></div><img src={listing.screenshot.trim()} alt={`Synthetic screenshot for ${listing.productName}`} className="mt-4 w-full rounded-xl border border-slate-200 bg-slate-50" /><dl className="mt-4 space-y-3 text-sm"><div><dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Source URL</dt><dd className="mt-1 break-all"><a href={listing.sourceUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-blue-700 underline focus-visible:ring-2 focus-visible:ring-blue-600">{listing.sourceUrl}<ExternalLink className="h-3.5 w-3.5" /></a></dd></div><div><dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Captured</dt><dd className="mt-1 flex items-center gap-2 text-slate-700"><Clock3 className="h-4 w-4" />{new Date(listing.observedAt).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}</dd></div></dl></Card>
          <Card className="p-5 sm:p-6"><h2 className="text-base font-semibold">Repeat observation history</h2>{selectedCase.history.length === 0 ? <p className="mt-4 text-sm text-slate-500">No prior observation in this demo case.</p> : <div className="mt-5 space-y-4">{selectedCase.history.map((item) => { const observed = observedPerUnit(item.mrp, item.unitsInPack); const difference = calculationView(reference.ceilingPricePerUnit, reference.gstPercent, item.mrp, item.unitsInPack).discrepancy; return <div key={item.id} className="rounded-xl border border-slate-200 p-4"><div className="flex flex-wrap justify-between gap-2"><div><p className="text-sm font-semibold">{item.label}</p><p className="mt-1 text-xs text-slate-500">{new Date(item.observedAt).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}</p></div><div className="text-right"><p className="text-sm font-semibold">{formatCurrency(observed)} / unit</p><p className="text-xs font-semibold text-red-700">{formatPercent(difference)}</p></div></div><p className="mt-2 font-mono text-[10px] text-slate-500">{formatCurrency(item.mrp)} ÷ {item.unitsInPack} units = {formatCurrency(observed, 4)}</p></div>; })}</div>}</Card>
        </div>

        <div className="space-y-6">
          <Card className="p-5 sm:p-6"><h2 className="text-base font-semibold">Plain-language calculation</h2><p className="mt-1 text-sm text-slate-600">Unrounded values are used; display rounding happens last.</p><ol className="mt-5 space-y-3">{steps.map((step, index) => <li key={step.label} className={`rounded-xl border p-4 ${index === steps.length - 1 ? "border-red-200 bg-red-50/60" : "border-slate-200 bg-slate-50"}`}><div className="flex items-start gap-3"><span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-white text-xs font-bold text-blue-700 shadow-sm">{index + 1}</span><div className="min-w-0 flex-1"><div className="flex flex-wrap justify-between gap-2"><strong className="text-sm">{step.label}</strong><strong className={index === steps.length - 1 ? "text-sm text-red-700" : "text-sm"}>{step.value}</strong></div><p className="mt-2 break-words font-mono text-[11px] leading-5 text-slate-600">{step.formula}</p></div></div></li>)}</ol></Card>
          <Card className="p-5 sm:p-6"><h2 className="text-base font-semibold">Reviewer decision</h2><p className="mt-1 text-sm text-slate-600">Mock API actions update only in-memory state.</p><div className="mt-5 grid gap-2"><FocusButton onClick={() => void onReview("confirm")} className="bg-blue-600 text-white hover:bg-blue-700"><CheckCircle2 className="h-4 w-4" />Confirm for review</FocusButton><FocusButton onClick={() => void onReview("needs_more_evidence")} className="border border-amber-300 bg-amber-50 text-amber-950"><ImagePlus className="h-4 w-4" />Need more evidence</FocusButton><FocusButton onClick={() => void onReview("dismiss")} className="border border-slate-300 bg-white text-slate-800"><XCircle className="h-4 w-4" />Dismiss</FocusButton></div>{selectedCase.reviews.length > 0 && <div className="mt-5 border-t border-slate-200 pt-4"><h3 className="text-sm font-semibold">Review history</h3><ul className="mt-2 space-y-2 text-xs text-slate-600">{selectedCase.reviews.map((review) => <li key={review.id}><strong>{review.reviewer}</strong> · {review.action.replaceAll("_", " ")} · {review.note}</li>)}</ul></div>}</Card>
        </div>
      </div>
    </div>
  );
}
