import { useEffect, useRef, useState } from "react";
import { Check, Circle, LoaderCircle, Play } from "lucide-react";
import { MOCK_SCAN } from "../data/mock";
import type { PharmacySite, ScanResult } from "../types";
import { Card, FocusButton, cx } from "../components/ui";
import { startScan } from "../api/client";

export function ScanPage() {
  const demoSites: PharmacySite[] = ["Demo Pharmacy A", "Demo Pharmacy B", "Demo Pharmacy C"];
  const [medicine, setMedicine] = useState<string>(MOCK_SCAN.medicines[0]);
  const [sites, setSites] = useState<PharmacySite[]>([...demoSites]);
  const [activeStep, setActiveStep] = useState(-1);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<ScanResult | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => () => { if (timer.current) window.clearInterval(timer.current); }, []);

  const run = async () => {
    if (timer.current) window.clearInterval(timer.current);
    const next = await startScan({ medicine, sites });
    setResult(next);
    setRunning(true);
    setActiveStep(0);
    let current = 0;
    timer.current = window.setInterval(() => {
      current += 1;
      setActiveStep(current);
      if (current >= next.stages.length) {
        if (timer.current) window.clearInterval(timer.current);
        setRunning(false);
      }
    }, 620);
  };

  const toggleSite = (site: PharmacySite) => setSites((current) => current.includes(site) ? current.filter((item) => item !== site) : [...current, site]);
  const complete = result !== null && activeStep >= result.stages.length;
  const stages = result?.stages ?? MOCK_SCAN.stages;

  return (
    <div className="grid gap-6 xl:grid-cols-[0.85fr_1.15fr]">
      <Card className="p-5 sm:p-6">
        <h2 className="text-base font-semibold">Scan configuration</h2><p className="mt-1 text-sm text-slate-600">Demo controls call the mock API client only.</p>
        <label className="mt-6 block text-sm font-semibold" htmlFor="medicine">Medicine family</label>
        <select id="medicine" value={medicine} onChange={(event) => setMedicine(event.target.value)} className="mt-2 h-11 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm focus:border-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-200">{MOCK_SCAN.medicines.map((item) => <option key={item}>{item}</option>)}</select>
        <fieldset className="mt-6"><legend className="text-sm font-semibold">Fictional pharmacy sites</legend><div className="mt-2 space-y-2">{demoSites.map((site, index) => <label key={site} className={cx("flex min-h-12 cursor-pointer items-center justify-between rounded-xl border px-3", sites.includes(site) ? "border-blue-300 bg-blue-50/40" : "border-slate-200")}><span className="flex items-center gap-3"><input type="checkbox" checked={sites.includes(site)} onChange={() => toggleSite(site)} className="h-4 w-4 accent-blue-600" /><span className="text-sm font-medium">{site}</span></span><span className="text-xs text-slate-500">demo-{String.fromCharCode(97 + index)}.example</span></label>)}</div></fieldset>
        <div className="mt-5 rounded-xl border border-blue-200 bg-blue-50 p-3 text-xs leading-5 text-blue-900"><strong>Demo mode:</strong> no live site is contacted.</div>
        <FocusButton onClick={run} disabled={running || sites.length === 0} className="mt-5 w-full bg-blue-600 text-white hover:bg-blue-700">{running ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}{running ? "Scan in progress" : "Start scan"}</FocusButton>
      </Card>

      <Card className="p-5 sm:p-6" aria-live="polite">
        <div className="flex items-start justify-between gap-4"><div><h2 className="text-base font-semibold">Live progress</h2><p className="mt-1 text-sm text-slate-600">{sites.length} selected sites · {medicine}</p></div><span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold">{complete ? "Complete" : running ? `Stage ${activeStep + 1} / ${stages.length}` : "Ready"}</span></div>
        <ol className="mt-7 space-y-1">{stages.map((stage, index) => { const done = activeStep > index || complete; const active = running && activeStep === index; return <li key={stage.id} className="relative flex gap-4 pb-6 last:pb-0">{index < stages.length - 1 && <span className={cx("absolute left-[15px] top-8 h-[calc(100%-16px)] w-0.5", done ? "bg-blue-600" : "bg-slate-200")} />}<span className={cx("relative z-10 grid h-8 w-8 shrink-0 place-items-center rounded-full border-2 bg-white", done ? "border-blue-600 bg-blue-600 text-white" : active ? "border-blue-600 text-blue-600" : "border-slate-300 text-slate-400")}>{done ? <Check className="h-4 w-4" /> : active ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Circle className="h-3 w-3" />}</span><div><p className="text-sm font-semibold">{stage.label}</p><p className="mt-0.5 text-xs text-slate-500">{stage.detail}</p></div></li>; })}</ol>
        {complete && result && <div className="mt-6 rounded-xl border border-green-200 bg-green-50 p-4 text-sm text-green-900"><strong>Demo scan complete</strong><p className="mt-1 text-xs">{result.extracted} extracted · {result.matched} matched · {result.caseIds.length} cases represented</p><p className="mt-1 font-mono text-[11px]">{result.extracted} = {result.request.sites.length} selected sites × 8 cached listings</p></div>}
      </Card>
    </div>
  );
}
