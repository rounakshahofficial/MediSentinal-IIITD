import { useEffect, useRef, type KeyboardEvent, type ReactNode } from "react";
import { Camera, ClipboardCheck, FileSearch, LayoutDashboard, ScanLine, SearchCheck, ShieldCheck } from "lucide-react";
import { MOCK_META } from "../data/mock";
import type { DemoState, Screen } from "../types";
import { DemoBadge, cx } from "./ui";

const TABS: Array<{ id: Screen; label: string; icon: typeof LayoutDashboard }> = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "scan", label: "Scan", icon: ScanLine },
  { id: "photo", label: "Photo Check", icon: Camera },
  { id: "queue", label: "Case Queue", icon: ClipboardCheck },
  { id: "match", label: "Match Check", icon: SearchCheck },
  { id: "dossier", label: "Dossier", icon: FileSearch },
];

const TITLES: Record<Screen, { title: string; description: string }> = {
  overview: { title: "Compliance overview", description: "See what needs reviewer attention first." },
  scan: { title: "Start a compliance scan", description: "Discover, extract, match, calculate and create a review case." },
  photo: { title: "Photo check", description: "Verify a medicine pack photo before trusting extracted fields." },
  queue: { title: "Case queue", description: "Sort potential discrepancies by urgency and evidence quality." },
  match: { title: "Match check", description: "Compare every required field against the placeholder reference." },
  dossier: { title: "Evidence dossier", description: "Review the source, calculation and repeat history before deciding." },
};

interface AppShellProps {
  screen: Screen;
  demoState: DemoState;
  queueCount: number;
  onScreenChange: (screen: Screen) => void;
  onDemoStateChange: (state: DemoState) => void;
  children: ReactNode;
}

export function AppShell({ screen, demoState, queueCount, onScreenChange, onDemoStateChange, children }: AppShellProps) {
  const title = TITLES[screen];
  const heading = useRef<HTMLHeadingElement>(null);
  const previousScreen = useRef(screen);
  const tabButtons = useRef<Array<HTMLButtonElement | null>>([]);

  useEffect(() => {
    if (previousScreen.current !== screen) {
      heading.current?.focus({ preventScroll: true });
      previousScreen.current = screen;
    }
  }, [screen]);

  const handleTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight") nextIndex = (index + 1) % TABS.length;
    if (event.key === "ArrowLeft") nextIndex = (index - 1 + TABS.length) % TABS.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = TABS.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    const nextTab = TABS[nextIndex];
    tabButtons.current[nextIndex]?.focus();
    onScreenChange(nextTab.id);
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-950">
      <style>{`@keyframes grow { from { transform: scaleX(0); } to { transform: scaleX(1); } @media (prefers-reduced-motion: reduce) { *,*::before,*::after { animation-duration: .01ms !important; scroll-behavior: auto !important; transition-duration: .01ms !important; } }`}</style>
      <a href="#main-content" className="fixed left-4 top-3 z-[100] -translate-y-20 rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white shadow-lg transition-transform focus:translate-y-0 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:ring-offset-2">Skip to content</a>
      <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1440px] items-center justify-between gap-4 px-4 py-3 sm:px-6 lg:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-blue-600 text-white shadow-sm"><ShieldCheck className="h-5 w-5" /></span>
            <div className="min-w-0">
              <div className="flex items-center gap-2"><span className="truncate text-base font-bold">MediSentinel</span><span className="hidden truncate rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-semibold text-slate-700 sm:inline">{MOCK_META.scope}</span></div>
              <p className="truncate text-xs text-slate-600">{MOCK_META.notice}</p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2"><DemoBadge /><span className="hidden text-xs text-slate-600 xl:inline">Updated {MOCK_META.updated}</span></div>
        </div>
        <nav className="mx-auto max-w-[1440px] overflow-x-auto px-2 sm:px-4 lg:px-6" aria-label="Product screens">
          <div className="flex min-w-max gap-1" role="tablist" aria-label="MediSentinel workflow">
            {TABS.map((tab, index) => {
              const Icon = tab.icon;
              const active = screen === tab.id;
              return (
                <button
                  key={tab.id}
                  ref={(element) => { tabButtons.current[index] = element; }}
                  id={`tab-${tab.id}`}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  aria-controls={`panel-${tab.id}`}
                  tabIndex={active ? 0 : -1}
                  onClick={() => onScreenChange(tab.id)}
                  onKeyDown={(event) => handleTabKeyDown(event, index)}
                  className={cx("flex min-h-12 items-center gap-2 border-b-2 px-3 text-sm font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-600", active ? "border-blue-600 text-blue-800" : "border-transparent text-slate-700 hover:border-slate-400 hover:text-slate-950")}
                >
                  <Icon className="h-4 w-4" aria-hidden="true" />{tab.label}{tab.id === "queue" && <span className={cx("rounded-full px-2 py-0.5 text-[11px]", active ? "bg-blue-100 text-blue-900" : "bg-slate-200 text-slate-800")}>{queueCount}</span>}
                </button>
              );
            })}
          </div>
        </nav>
      </header>

      <main id="main-content" tabIndex={-1} className="mx-auto max-w-[1440px] px-4 py-6 outline-none sm:px-6 lg:px-8 lg:py-8">
        <section id={`panel-${screen}`} role="tabpanel" aria-labelledby={`tab-${screen}`} tabIndex={0}>
          <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div><p className="text-xs font-bold uppercase tracking-[0.16em] text-blue-800">Reviewer workspace</p><h1 ref={heading} tabIndex={-1} className="mt-2 text-2xl font-bold outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2 sm:text-3xl">{title.title}</h1><p className="mt-2 text-sm text-slate-700">{title.description}</p></div>
            <label className="flex items-center gap-2 text-xs font-semibold text-slate-700">Preview state<select value={demoState} onChange={(event) => onDemoStateChange(event.target.value as DemoState)} className="h-10 rounded-lg border border-slate-400 bg-white px-3 text-sm focus:border-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-200"><option value="ready">Ready</option><option value="loading">Loading</option><option value="empty">Empty</option><option value="error">Error</option></select></label>
          </div>
          {children}
        </section>
      </main>

      <footer className="mt-10 border-t border-slate-200 bg-white"><div className="mx-auto flex max-w-[1440px] flex-col gap-2 px-4 py-5 text-xs text-slate-600 sm:flex-row sm:justify-between sm:px-6 lg:px-8"><p>MediSentinel surfaces potential discrepancies for human verification.</p><p>Demo data · No live pharmacy or regulator systems connected</p></div></footer>
    </div>
  );
}
