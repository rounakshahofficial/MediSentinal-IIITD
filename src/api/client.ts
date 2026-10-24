import { MOCK_CASES, MOCK_PHOTO_CHECK, MOCK_SCAN, MOCK_STATS } from "../data/mock";
import type {
  Case,
  PhotoCheck,
  PhotoCheckRequest,
  ReviewRequest,
  ScanRequest,
  ScanResult,
  Stats,
} from "../types";

export const USE_MOCK = true;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    throw new Error(`Request failed with HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

const copy = <T>(value: T): T => structuredClone(value);

export async function getStats(): Promise<Stats> {
  return USE_MOCK ? copy(MOCK_STATS) : request<Stats>("/api/stats");
}

export async function getCases(): Promise<Case[]> {
  return USE_MOCK ? copy(MOCK_CASES) : request<Case[]>("/api/cases");
}

export async function getCase(caseId: string): Promise<Case> {
  if (!USE_MOCK) return request<Case>(`/api/cases/${encodeURIComponent(caseId)}`);
  const found = MOCK_CASES.find((item) => item.id === caseId);
  if (!found) throw new Error(`Demo case ${caseId} was not found`);
  return copy(found);
}

export async function postReview(caseId: string, payload: ReviewRequest): Promise<Case> {
  if (!USE_MOCK) {
    return request<Case>(`/api/cases/${encodeURIComponent(caseId)}/review`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }
  const current = await getCase(caseId);
  const status = payload.action === "confirm"
    ? "confirmed_for_review"
    : payload.action === "dismiss"
      ? "dismissed"
      : "needs_more_evidence";
  return {
    ...current,
    status,
    reviews: [
      ...current.reviews,
      {
        id: `REV-DEMO-${current.reviews.length + 1}`,
        action: payload.action,
        reviewer: payload.reviewer,
        note: payload.note,
        createdAt: new Date().toISOString(),
      },
    ],
  };
}

export async function startScan(payload: ScanRequest): Promise<ScanResult> {
  if (!USE_MOCK) {
    return request<ScanResult>("/api/scans", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }
  const selectedStats = MOCK_STATS.sites.filter((item) => payload.sites.includes(item.site));
  const selectedCases = MOCK_CASES.filter((item) => payload.sites.includes(item.listing.site));
  return {
    request: copy(payload),
    stages: copy(MOCK_SCAN.stages),
    extracted: selectedStats.reduce((total, item) => total + item.scanned, 0),
    matched: selectedStats.reduce((total, item) => total + item.matched, 0),
    caseIds: selectedCases.map((item) => item.id),
  };
}

export async function postPhotoCheck(payload: PhotoCheckRequest): Promise<PhotoCheck> {
  if (!USE_MOCK) {
    return request<PhotoCheck>("/api/photo-checks", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }
  return {
    ...copy(MOCK_PHOTO_CHECK),
    image: payload.image,
    fields: copy(payload.fields),
  };
}
