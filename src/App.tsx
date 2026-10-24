import { useEffect, useMemo, useState } from "react";
import { AppShell } from "./components/AppShell";
import { EmptyState, ErrorState, LoadingState } from "./components/ui";
import { getCases, getStats, postReview } from "./api/client";
import type { Case, DemoState, ReviewAction, Screen, Stats } from "./types";
import { OverviewPage } from "./pages/OverviewPage";
import { ScanPage } from "./pages/ScanPage";
import { PhotoCheckPage } from "./pages/PhotoCheckPage";
import { CaseQueuePage } from "./pages/CaseQueuePage";
import { MatchCheckPage } from "./pages/MatchCheckPage";
import { DossierPage } from "./pages/DossierPage";

function parseHash(): { screen: Screen; caseId: string | null } {
  const hash = window.location.hash;
  const caseMatch = hash.match(/^#\/cases\/([^/]+)$/);
  if (caseMatch) return { screen: "dossier", caseId: decodeURIComponent(caseMatch[1]) };
  const matchMatch = hash.match(/^#\/match\/([^/]+)$/);
  if (matchMatch) return { screen: "match", caseId: decodeURIComponent(matchMatch[1]) };
  const screen = hash.replace(/^#\//, "") as Screen;
  return ["overview", "scan", "photo", "queue", "match", "dossier"].includes(screen)
    ? { screen, caseId: null }
    : { screen: "overview", caseId: null };
}

function App() {
  const initialRoute = useMemo(parseHash, []);
  const [screen, setScreen] = useState<Screen>(initialRoute.screen);
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(initialRoute.caseId);
  const [demoState, setDemoState] = useState<DemoState>("ready");
  const [cases, setCases] = useState<Case[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [bootError, setBootError] = useState(false);

  const load = async () => {
    setBootError(false);
    try {
      const [nextStats, nextCases] = await Promise.all([getStats(), getCases()]);
      setStats(nextStats);
      setCases(nextCases);
      setSelectedCaseId((current) => current && nextCases.some((item) => item.id === current) ? current : nextCases[0]?.id ?? null);
    } catch {
      setBootError(true);
    }
  };

  useEffect(() => { void load(); }, []);

  useEffect(() => {
    const onHashChange = () => {
      const route = parseHash();
      setScreen(route.screen);
      if (route.caseId) setSelectedCaseId(route.caseId);
      setDemoState("ready");
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const selectedCase = cases.find((item) => item.id === selectedCaseId) ?? cases[0] ?? null;

  const navigate = (nextScreen: Screen, caseId = selectedCase?.id ?? null) => {
    setScreen(nextScreen);
    setDemoState("ready");
    if (caseId) setSelectedCaseId(caseId);
    const nextHash = nextScreen === "dossier" && caseId
      ? `#/cases/${encodeURIComponent(caseId)}`
      : nextScreen === "match" && caseId
        ? `#/match/${encodeURIComponent(caseId)}`
        : `#/${nextScreen}`;
    if (window.location.hash !== nextHash) window.location.hash = nextHash;
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const handleReview = async (action: ReviewAction) => {
    if (!selectedCase) return;
    const updated = await postReview(selectedCase.id, {
      action,
      reviewer: "Demo Reviewer",
      note: "Local demo action; not persisted to a backend",
    });
    setCases((current) => current.map((item) => item.id === updated.id ? updated : item));
  };

  let content;
  if (bootError) content = <ErrorState onRetry={() => void load()} />;
  else if (!stats || cases.length === 0) content = <LoadingState />;
  else if (demoState === "loading") content = <LoadingState />;
  else if (demoState === "empty") content = <EmptyState onReset={() => setDemoState("ready")} />;
  else if (demoState === "error") content = <ErrorState onRetry={() => setDemoState("ready")} />;
  else if (screen === "overview") content = <OverviewPage stats={stats} cases={cases} onOpenCase={(id) => navigate("dossier", id)} />;
  else if (screen === "scan") content = <ScanPage />;
  else if (screen === "photo") content = <PhotoCheckPage />;
  else if (screen === "queue") content = <CaseQueuePage cases={cases} onOpenDossier={(id) => navigate("dossier", id)} onOpenMatch={(id) => navigate("match", id)} />;
  else if (screen === "match" && selectedCase) content = <MatchCheckPage selectedCase={selectedCase} cases={cases} onSelectCase={(id) => navigate("match", id)} />;
  else if (selectedCase) content = <DossierPage selectedCase={selectedCase} onReview={handleReview} />;
  else content = <EmptyState onReset={() => navigate("overview")} />;

  return <AppShell screen={screen} demoState={demoState} queueCount={cases.length} onScreenChange={(next) => navigate(next)} onDemoStateChange={setDemoState}>{content}</AppShell>;
}

export default App;
