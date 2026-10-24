export type PharmacySite =
  | "Demo Pharmacy A"
  | "Demo Pharmacy B"
  | "Demo Pharmacy C";

export type CaseStatus =
  | "potential_discrepancy"
  | "needs_verification"
  | "confirmed_for_review"
  | "dismissed"
  | "needs_more_evidence";

export type MatchStatus = "matched" | "uncertain" | "no_match";
export type MatchFieldState = "check" | "warning" | "cross";
export type ReviewAction = "confirm" | "dismiss" | "needs_more_evidence";
export type Screen = "overview" | "scan" | "photo" | "queue" | "match" | "dossier";
export type DemoState = "ready" | "loading" | "empty" | "error";
export type SortKey = "priority" | "discrepancy" | "site";

export interface Listing {
  id: string;
  site: PharmacySite;
  sourceUrl: string;
  productName: string;
  compositionRaw: string;
  packSizeRaw: string;
  mrp: number;
  sellingPrice: number | null;
  unitsInPack: number | null;
  observedAt: string;
  screenshot: string;
}

export interface Reference {
  id: string;
  ingredient: string;
  strength: string;
  dosageForm: string;
  unit: string;
  ceilingPricePerUnit: number;
  gstPercent: number;
  sourceOrder: string;
  effectiveFrom: string;
  version: string;
}

export interface MatchField {
  field: "Ingredient" | "Strength" | "Dosage form" | "Pack size";
  listingValue: string;
  referenceValue: string;
  state: MatchFieldState;
  note: string;
}

export interface Match {
  id: string;
  status: MatchStatus;
  confidence: number;
  parsedIngredient: string | null;
  parsedStrength: string | null;
  parsedDosageForm: string | null;
  unitsInPack: number | null;
  fields: MatchField[];
  reasons: string[];
}

export interface Review {
  id: string;
  action: ReviewAction;
  reviewer: string;
  note: string;
  createdAt: string;
}

export interface PriorityParts {
  discrepancy: number;
  confidence: number;
  evidence: number;
  recurrence: number;
}

export interface ObservationHistory {
  id: string;
  observedAt: string;
  mrp: number;
  unitsInPack: number;
  label: string;
}

export interface Case {
  id: string;
  listing: Listing;
  reference: Reference;
  match: Match;
  status: CaseStatus;
  priorityParts: PriorityParts;
  isRecurrent: boolean;
  history: ObservationHistory[];
  reviews: Review[];
}

export interface PhotoField {
  id: "product" | "ingredient" | "strength" | "form" | "pack" | "mrp";
  label: string;
  value: string;
  confidence: number;
}

export interface PhotoCheck {
  id: string;
  image: string;
  fields: PhotoField[];
  listing: Listing;
  reference: Reference;
  status: "potential_discrepancy" | "needs_verification" | "within_tolerance";
  imageQuality: "demo_not_evaluated";
}

export interface SiteSummary {
  site: PharmacySite;
  scanned: number;
  matched: number;
  needsVerification: number;
}

export interface Stats {
  sites: SiteSummary[];
  generatedAt: string;
}

export interface ScanStage {
  id: "discover" | "extract" | "match" | "calculate" | "case_created";
  label: string;
  detail: string;
}

export interface ScanRequest {
  medicine: string;
  sites: PharmacySite[];
}

export interface ScanResult {
  request: ScanRequest;
  stages: ScanStage[];
  extracted: number;
  matched: number;
  caseIds: string[];
}

export interface PhotoCheckRequest {
  image: string;
  fields: PhotoField[];
}

export interface ReviewRequest {
  action: ReviewAction;
  reviewer: string;
  note: string;
}
