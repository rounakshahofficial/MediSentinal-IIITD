import { useMemo, useState } from "react";
import { ArrowDownUp, ChevronRight, SearchCheck } from "lucide-react";
import type { Case, SortKey } from "../types";
import { calculationView, formatPercent, priorityFormula, priorityScore } from "../lib/calc";
import { Card, FocusButton, PriorityHelp, StatusChip, cx } from "../components/ui";

interface CaseQueuePageProps {
  cases: Case[];
  onOpenDossier: (caseId: string) => void;
  onOpenMatch: (caseId: string) => void;
}

export function CaseQueuePage({ cases, onOpenDossier, onOpenMatch }: CaseQueuePageProps) {
  const [sortKey, setSortKey] = useState<SortKey>("priority");
  const [descending, setDescending] = useState(true);
  const rows = useMemo(() => [...cases].sort((a, b) => {
    const aCalc = calculationView(a.reference.ceilingPricePerUnit, a.reference.gstPercent, a.listing.mrp, a.listing.unitsInPack);
    const bCalc = calculationView(b.reference.ceilingPricePerUnit, b.reference.gstPercent, b.listing.mrp, b.listing.unitsInPack);
    const left = sortKey === "site" ? a.listing.site : sortKey === "discrepancy" ? aCalc.discrepancy ?? -Infinity : priorityScore(a.priorityParts);
    const right = sortKey === "site" ? b.listing.site : sortKey === "discrepancy" ? bCalc.discrepancy ?? -Infinity : priorityScore(b.priorityParts);
    const comparison = typeof left === "string" ? left.localeCompare(String(right)) : left - Number(right);
    return descending ? -comparison : comparison;
  }), [cases, sortKey, descending]);

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-col gap-4 border-b border-slate-200 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5"><div><h2 className="text-base font-semibold">Reviewer queue</h2><p className="mt-1 text-sm text-slate-600">{cases.length} demo cases · each result is calculated from raw inputs</p></div><div className="flex flex-wrap gap-2"><label className="sr-only" htmlFor="queue-sort">Sort cases by</label><select id="queue-sort" value={sortKey} onChange={(event) => setSortKey(event.target.value as SortKey)} className="h-10 rounded-lg border border-slate-300 bg-white px-3 text-sm focus:border-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-200"><option value="priority">Priority score</option><option value="discrepancy">Discrepancy %</option><option value="site">Site</option></select><FocusButton onClick={() => setDescending((value) => !value)} className="border border-slate-300 bg-white px-3 text-slate-700"><ArrowDownUp className="h-4 w-4" />{descending ? "High first" : "Low first"}</FocusButton></div></div>
      <div className="hidden overflow-x-auto md:block"><table className="w-full min-w-[980px] text-left text-sm"><thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500"><tr><th className="px-5 py-3">Case</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">Site</th><th className="px-4 py-3 text-right">Priority</th><th className="px-4 py-3 text-right">Potential difference</th><th className="px-5 py-3 text-right">Actions</th></tr></thead><tbody className="divide-y divide-slate-100">{rows.map((item) => {
        const calc = calculationView(item.reference.ceilingPricePerUnit, item.reference.gstPercent, item.listing.mrp, item.listing.unitsInPack);
        const score = priorityScore(item.priorityParts);
        return <tr key={item.id} className="hover:bg-slate-50"><td className="px-5 py-4"><p className="font-semibold">{item.id}</p><p className="mt-1 text-xs text-slate-500">{item.listing.productName}</p></td><td className="px-4 py-4"><StatusChip status={item.status} /></td><td className="px-4 py-4">{item.listing.site}</td><td className="px-4 py-4 text-right"><div className="inline-flex items-center gap-1.5"><strong>{score} / 100</strong><PriorityHelp formula={priorityFormula(item.priorityParts)} /></div></td><td className="px-4 py-4 text-right">{calc.discrepancy === null ? <span className="font-semibold text-amber-800">STOP</span> : <><strong className="text-red-700">{formatPercent(calc.discrepancy)}</strong><p className="mt-1 font-mono text-[10px] text-slate-500">{calc.discrepancyFormula}</p></>}</td><td className="px-5 py-4"><div className="flex justify-end gap-2"><FocusButton onClick={() => onOpenMatch(item.id)} className="border border-slate-300 bg-white px-3 text-slate-800"><SearchCheck className="h-4 w-4" />Match</FocusButton><FocusButton onClick={() => onOpenDossier(item.id)} className="bg-blue-600 px-3 text-white">Dossier <ChevronRight className="h-4 w-4" /></FocusButton></div></td></tr>;
      })}</tbody></table></div>
      <div className="divide-y divide-slate-100 md:hidden">{rows.map((item) => {
        const calc = calculationView(item.reference.ceilingPricePerUnit, item.reference.gstPercent, item.listing.mrp, item.listing.unitsInPack);
        return <article key={item.id} className="p-4"><div className="flex items-start justify-between gap-3"><div><p className="font-semibold">{item.id} · {item.listing.productName}</p><p className="mt-1 text-xs text-slate-500">{item.listing.site}</p></div><PriorityHelp formula={priorityFormula(item.priorityParts)} /></div><div className="mt-3"><StatusChip status={item.status} /></div><dl className="mt-4 grid grid-cols-2 gap-3 rounded-xl bg-slate-50 p-3 text-xs"><div><dt className="text-slate-500">Priority</dt><dd className="mt-1 font-semibold">{priorityScore(item.priorityParts)} / 100</dd></div><div><dt className="text-slate-500">Potential difference</dt><dd className={cx("mt-1 font-semibold", calc.discrepancy === null ? "text-amber-800" : "text-red-700")}>{calc.discrepancy === null ? "STOP" : formatPercent(calc.discrepancy)}</dd></div></dl><p className="mt-2 font-mono text-[10px] text-slate-500">{calc.discrepancyFormula}</p><div className="mt-4 grid grid-cols-2 gap-2"><FocusButton onClick={() => onOpenMatch(item.id)} className="border border-slate-300 bg-white px-2 text-slate-800">Match</FocusButton><FocusButton onClick={() => onOpenDossier(item.id)} className="bg-blue-600 px-2 text-white">Dossier</FocusButton></div></article>;
      })}</div>
    </Card>
  );
}
