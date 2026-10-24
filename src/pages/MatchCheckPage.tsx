import { AlertTriangle, Check, X } from "lucide-react";
import type { Case, MatchFieldState } from "../types";
import { calculationView, formatPercent } from "../lib/calc";
import { Card, cx } from "../components/ui";

function MatchStateIcon({ state }: { state: MatchFieldState }) {
  if (state === "check") return <span className="grid h-7 w-7 place-items-center rounded-full bg-green-50 text-green-700" aria-label="Fields agree"><Check className="h-4 w-4" /></span>;
  if (state === "warning") return <span className="grid h-7 w-7 place-items-center rounded-full bg-amber-50 text-amber-800" aria-label="Field needs verification"><AlertTriangle className="h-4 w-4" /></span>;
  return <span className="grid h-7 w-7 place-items-center rounded-full bg-red-50 text-red-700" aria-label="Fields do not agree"><X className="h-4 w-4" /></span>;
}

interface MatchCheckPageProps {
  selectedCase: Case;
  cases: Case[];
  onSelectCase: (caseId: string) => void;
}

export function MatchCheckPage({ selectedCase, cases, onSelectCase }: MatchCheckPageProps) {
  const stopped = selectedCase.match.status !== "matched" || selectedCase.match.fields.some((field) => field.state !== "check");
  const calc = calculationView(selectedCase.reference.ceilingPricePerUnit, selectedCase.reference.gstPercent, selectedCase.listing.mrp, selectedCase.listing.unitsInPack);
  return (
    <div className="space-y-6">
      <label className="flex max-w-xl flex-col gap-2 text-sm font-semibold">Selected case<select value={selectedCase.id} onChange={(event) => onSelectCase(event.target.value)} className="h-11 rounded-lg border border-slate-300 bg-white px-3 font-normal focus:border-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-200">{cases.map((item) => <option key={item.id} value={item.id}>{item.id} · {item.listing.productName} · {item.listing.site}</option>)}</select></label>
      <Card className="overflow-hidden">
        <div className="border-b border-slate-200 p-5 sm:p-6"><div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"><div><h2 className="text-base font-semibold">Required-field comparison</h2><p className="mt-1 text-sm text-slate-600">{selectedCase.listing.productName} · {selectedCase.listing.site}</p><p className="mt-1 text-xs text-slate-500">{selectedCase.reference.sourceOrder}</p></div><span className={cx("rounded-full border px-3 py-1 text-xs font-semibold", stopped ? "border-amber-200 bg-amber-50 text-amber-900" : "border-green-200 bg-green-50 text-green-800")}>{selectedCase.match.confidence}% confidence · {stopped ? "STOP" : "MATCHED"}</span></div></div>
        <div className="grid grid-cols-[minmax(90px,.7fr)_minmax(120px,1fr)_minmax(120px,1fr)_44px] gap-2 border-b border-slate-200 bg-slate-50 px-4 py-3 text-xs font-semibold uppercase tracking-wide text-slate-500 sm:grid-cols-[1fr_1.4fr_1.4fr_52px] sm:px-6"><span>Field</span><span>Listing</span><span>Placeholder reference</span><span className="sr-only">Result</span></div>
        <div className="divide-y divide-slate-100">{selectedCase.match.fields.map((field) => <div key={field.field} className="grid grid-cols-[minmax(90px,.7fr)_minmax(120px,1fr)_minmax(120px,1fr)_44px] gap-2 px-4 py-4 text-sm sm:grid-cols-[1fr_1.4fr_1.4fr_52px] sm:px-6"><div><strong>{field.field}</strong><p className="mt-1 hidden text-xs text-slate-500 sm:block">{field.note}</p></div><span className="break-words text-slate-700">{field.listingValue}</span><span className="break-words text-slate-700">{field.referenceValue}</span><MatchStateIcon state={field.state} /></div>)}</div>
      </Card>
      <Card className={stopped ? "border-amber-200 bg-amber-50 p-5" : "border-green-200 bg-green-50 p-5"}><div className="flex items-start gap-3">{stopped ? <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-800" /> : <Check className="mt-0.5 h-5 w-5 shrink-0 text-green-700" />}<div><h2 className="text-sm font-semibold">{stopped ? "Calculation stopped safely" : `Matched · ${formatPercent(calc.discrepancy)} potential difference`}</h2><p className="mt-2 font-mono text-xs leading-5">{stopped ? "Required fields must agree and units_in_pack must be a positive integer." : calc.discrepancyFormula}</p></div></div></Card>
    </div>
  );
}
