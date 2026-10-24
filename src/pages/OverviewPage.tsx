import { ChevronRight, ShieldCheck } from "lucide-react";
import type { Case, Stats } from "../types";
import { calculationView, formatNumber, formatPercent, priorityFormula, priorityScore } from "../lib/calc";
import { Card, FocusButton, StatusChip } from "../components/ui";

interface OverviewPageProps {
  stats: Stats;
  cases: Case[];
  onOpenCase: (caseId: string) => void;
}

export function OverviewPage({ stats, cases, onOpenCase }: OverviewPageProps) {
  const totalScanned = stats.sites.reduce((total, site) => total + site.scanned, 0);
  const totalMatched = stats.sites.reduce((total, site) => total + site.matched, 0);
  const totalNeedsVerification = stats.sites.reduce((total, site) => total + site.needsVerification, 0);
  const activeCases = cases.filter((item) => item.status === "potential_discrepancy" || item.status === "confirmed_for_review");
  const highestPriority = [...activeCases].sort((a, b) => priorityScore(b.priorityParts) - priorityScore(a.priorityParts))[0];

  const counts = [
    { label: "Listings scanned", value: totalScanned, formula: `${stats.sites.map((site) => site.scanned).join(" + ")} site listings = ${totalScanned}`, tone: "text-blue-700" },
    { label: "Deterministic matches", value: totalMatched, formula: `${totalMatched} ÷ ${totalScanned} × 100 = ${formatPercent((totalMatched / totalScanned) * 100, 1, false)}`, tone: "text-green-700" },
    { label: "Potential discrepancies", value: activeCases.length, formula: `${activeCases.length} active flagged cases ÷ ${totalMatched} matches = ${formatPercent((activeCases.length / totalMatched) * 100, 1, false)}`, tone: "text-red-700" },
    { label: "Needs verification", value: totalNeedsVerification, formula: `${stats.sites.map((site) => site.needsVerification).join(" + ")} site items = ${totalNeedsVerification}`, tone: "text-amber-800" },
  ];

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {counts.map((item) => <Card key={item.label} className="p-5"><p className="text-sm font-medium text-slate-600">{item.label}</p><p className={`mt-2 text-3xl font-bold tabular-nums ${item.tone}`}>{item.value}</p><p className="mt-2 font-mono text-[11px] leading-5 text-slate-500">{item.formula}</p></Card>)}
      </div>

      <div className="grid gap-6 lg:grid-cols-[1.35fr_0.65fr]">
        <Card className="p-5 sm:p-6">
          <div className="flex items-start justify-between gap-3"><div><h2 className="text-base font-semibold">Potential discrepancies by site</h2><p className="mt-1 text-sm text-slate-600">Active flagged cases ÷ scanned listings</p></div><span className="rounded-lg bg-slate-100 px-2.5 py-1 font-mono text-xs">n = {totalScanned}</span></div>
          <div className="mt-6 space-y-5" role="img" aria-label="Bar chart of potential discrepancies by fictional pharmacy site">
            {stats.sites.map((site) => {
              const flagged = activeCases.filter((item) => item.listing.site === site.site).length;
              const percent = (flagged / site.scanned) * 100;
              return <div key={site.site}><div className="mb-2 flex justify-between gap-3 text-sm"><span className="font-medium">{site.site}</span><span className="font-mono text-xs text-slate-600">{flagged} ÷ {site.scanned} × 100 = <strong className="text-red-700">{formatPercent(percent, 1, false)}</strong></span></div><div className="h-3 overflow-hidden rounded-full bg-slate-100"><div className="h-full origin-left animate-[grow_.55s_ease-out] rounded-full bg-blue-600" style={{ width: `${percent}%` }} /></div></div>;
            })}
          </div>
        </Card>

        {highestPriority && (() => {
          const score = priorityScore(highestPriority.priorityParts);
          const calc = calculationView(highestPriority.reference.ceilingPricePerUnit, highestPriority.reference.gstPercent, highestPriority.listing.mrp, highestPriority.listing.unitsInPack);
          return <Card className="flex flex-col p-5 sm:p-6"><div className="flex items-center gap-3"><span className="grid h-10 w-10 place-items-center rounded-xl bg-blue-50 text-blue-700"><ShieldCheck className="h-5 w-5" /></span><div><h2 className="text-base font-semibold">Next reviewer action</h2><p className="text-sm text-slate-600">Highest computed priority</p></div></div><div className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><strong>{highestPriority.id} · {highestPriority.listing.productName}</strong><StatusChip status={highestPriority.status} /></div><p className="mt-3 text-sm">Priority <strong>{formatNumber(score, 0)} / 100</strong></p><p className="mt-1 font-mono text-[11px] text-slate-500">{priorityFormula(highestPriority.priorityParts)}</p><p className="mt-2 font-mono text-[11px] text-slate-500">{calc.discrepancyFormula}</p></div><FocusButton onClick={() => onOpenCase(highestPriority.id)} className="mt-4 w-full bg-blue-600 text-white hover:bg-blue-700">Open dossier <ChevronRight className="h-4 w-4" /></FocusButton></Card>;
        })()}
      </div>
    </div>
  );
}
