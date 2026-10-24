import type {
  Case,
  Match,
  MatchField,
  PhotoCheck,
  Reference,
  ScanStage,
  SiteSummary,
  Stats,
} from "../types";

const REFERENCE_SOURCE = "REF-DEMO-001 (placeholder, replace with verified NPPA order)";

const svgDataUri = (title: string, subtitle: string, price: number, site: string) =>
  `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(`
    <svg xmlns="http://www.w3.org/2000/svg" width="900" height="560" viewBox="0 0 900 560">
      <defs><linearGradient id="g" x1="0" x2="1"><stop stop-color="#eff6ff"/><stop offset="1" stop-color="#dbeafe"/></linearGradient></defs>
      <rect width="900" height="560" fill="#e2e8f0"/><rect x="62" y="48" width="776" height="464" rx="22" fill="white" stroke="#94a3b8" stroke-width="3"/>
      <rect x="62" y="48" width="776" height="74" rx="22" fill="#2563eb"/><text x="92" y="94" font-family="Arial" font-size="27" font-weight="700" fill="white">${site} · DEMO CAPTURE</text>
      <rect x="92" y="160" width="150" height="270" rx="18" fill="url(#g)"/><circle cx="167" cy="250" r="43" fill="#2563eb"/>
      <path d="M146 250h42M167 229v42" stroke="white" stroke-width="12" stroke-linecap="round"/>
      <text x="282" y="205" font-family="Arial" font-size="38" font-weight="700" fill="#0f172a">${title}</text>
      <text x="282" y="252" font-family="Arial" font-size="22" fill="#475569">${subtitle}</text>
      <line x1="282" x2="770" y1="282" y2="282" stroke="#cbd5e1" stroke-width="2"/>
      <text x="282" y="340" font-family="Arial" font-size="27" fill="#0f172a">MRP ₹${price.toFixed(2)}</text>
      <text x="282" y="390" font-family="Arial" font-size="19" fill="#64748b">Synthetic evidence · not a live listing</text>
      <text x="92" y="478" font-family="Arial" font-size="17" fill="#1d4ed8">DEMO DATA</text>
    </svg>`)} `;

const reference = (
  id: string,
  strength: string,
  dosageForm: string,
  unit: string,
  ceilingPricePerUnit: number,
): Reference => ({
  id,
  ingredient: "Atorvastatin",
  strength,
  dosageForm,
  unit,
  ceilingPricePerUnit,
  gstPercent: 12,
  sourceOrder: REFERENCE_SOURCE,
  effectiveFrom: "2026-04-01",
  version: "DEMO-v1",
});

const references = {
  tablet5: reference("REF-5-TAB", "5 mg", "Tablet", "tablet", 3.46),
  tablet10: reference("REF-10-TAB", "10 mg", "Tablet", "tablet", 5.71),
  capsule10: reference("REF-10-CAP", "10 mg", "Capsule", "capsule", 6.15),
  tablet20: reference("REF-20-TAB", "20 mg", "Tablet", "tablet", 13.86),
  tablet40: reference("REF-40-TAB", "40 mg", "Tablet", "tablet", 20.11),
  tablet80: reference("REF-80-TAB", "80 mg", "Tablet", "tablet", 31.24),
} satisfies Record<string, Reference>;

const matchFields = (
  ingredient: string,
  strength: string,
  dosageForm: string,
  units: number | null,
  ref: Reference,
  strengthState: MatchField["state"] = "check",
): MatchField[] => [
  {
    field: "Ingredient",
    listingValue: ingredient,
    referenceValue: ref.ingredient,
    state: ingredient === ref.ingredient ? "check" : "cross",
    note: ingredient === ref.ingredient ? "Exact normalized match" : "Ingredient does not agree",
  },
  {
    field: "Strength",
    listingValue: strength,
    referenceValue: ref.strength,
    state: strengthState,
    note: strengthState === "check" ? "Exact normalized match" : "Title and composition conflict",
  },
  {
    field: "Dosage form",
    listingValue: dosageForm,
    referenceValue: ref.dosageForm,
    state: dosageForm === ref.dosageForm ? "check" : "cross",
    note: dosageForm === ref.dosageForm ? "Exact canonical form" : "Dosage form does not agree",
  },
  {
    field: "Pack size",
    listingValue: units === null ? "1 strip" : `${units} units`,
    referenceValue: `Price per 1 ${ref.unit}`,
    state: units === null ? "warning" : "check",
    note: units === null ? "Integer unit count is unclear" : "Integer pack count extracted",
  },
];

const matched = (
  id: string,
  strength: string,
  form: string,
  units: number,
  ref: Reference,
  confidence: number,
): Match => ({
  id,
  status: "matched",
  confidence,
  parsedIngredient: "Atorvastatin",
  parsedStrength: strength,
  parsedDosageForm: form,
  unitsInPack: units,
  fields: matchFields("Atorvastatin", strength, form, units, ref),
  reasons: ["Ingredient, strength and dosage form agree", "Integer pack count extracted"],
});

export const MOCK_CASES: Case[] = [
  {
    id: "MS-1042",
    listing: {
      id: "LIST-1042",
      site: "Demo Pharmacy A",
      sourceUrl: "https://demo-a.example/listings/demo-atorva-10",
      productName: "Demo Atorva-10",
      compositionRaw: "Atorvastatin 10 mg",
      packSizeRaw: "Strip of 10 tablets",
      mrp: 79.5,
      sellingPrice: 72,
      unitsInPack: 10,
      observedAt: "2026-10-23T16:00:00+05:30",
      screenshot: svgDataUri("Demo Atorva-10", "Atorvastatin 10 mg · 10 tablets", 79.5, "Demo Pharmacy A"),
    },
    reference: references.tablet10,
    match: matched("MATCH-1042", "10 mg", "Tablet", 10, references.tablet10, 98),
    status: "potential_discrepancy",
    priorityParts: { discrepancy: 29, confidence: 25, evidence: 18, recurrence: 15 },
    isRecurrent: true,
    history: [
      { id: "OBS-1042-B", observedAt: "2026-10-23T16:00:00+05:30", mrp: 79.5, unitsInPack: 10, label: "Repeat observation" },
      { id: "OBS-1042-A", observedAt: "2026-10-22T14:45:00+05:30", mrp: 78.5, unitsInPack: 10, label: "First observation" },
    ],
    reviews: [],
  },
  {
    id: "MS-1045",
    listing: {
      id: "LIST-1045",
      site: "Demo Pharmacy B",
      sourceUrl: "https://demo-b.example/listings/demo-atorva-40",
      productName: "Demo Atorva-40",
      compositionRaw: "Atorvastatin 40 mg",
      packSizeRaw: "Strip of 10 tablets",
      mrp: 298,
      sellingPrice: 276,
      unitsInPack: 10,
      observedAt: "2026-10-23T15:35:00+05:30",
      screenshot: svgDataUri("Demo Atorva-40", "Atorvastatin 40 mg · 10 tablets", 298, "Demo Pharmacy B"),
    },
    reference: references.tablet40,
    match: matched("MATCH-1045", "40 mg", "Tablet", 10, references.tablet40, 97),
    status: "potential_discrepancy",
    priorityParts: { discrepancy: 36, confidence: 25, evidence: 18, recurrence: 5 },
    isRecurrent: false,
    history: [{ id: "OBS-1045-A", observedAt: "2026-10-23T15:35:00+05:30", mrp: 298, unitsInPack: 10, label: "First observation" }],
    reviews: [],
  },
  {
    id: "MS-1049",
    listing: {
      id: "LIST-1049",
      site: "Demo Pharmacy C",
      sourceUrl: "https://demo-c.example/listings/demo-atorva-80",
      productName: "Demo Atorva-80",
      compositionRaw: "Atorvastatin 80 mg",
      packSizeRaw: "Strip of 10 tablets",
      mrp: 392,
      sellingPrice: 365,
      unitsInPack: 10,
      observedAt: "2026-10-23T15:10:00+05:30",
      screenshot: svgDataUri("Demo Atorva-80", "Atorvastatin 80 mg · 10 tablets", 392, "Demo Pharmacy C"),
    },
    reference: references.tablet80,
    match: matched("MATCH-1049", "80 mg", "Tablet", 10, references.tablet80, 96),
    status: "potential_discrepancy",
    priorityParts: { discrepancy: 21, confidence: 25, evidence: 18, recurrence: 5 },
    isRecurrent: false,
    history: [{ id: "OBS-1049-A", observedAt: "2026-10-23T15:10:00+05:30", mrp: 392, unitsInPack: 10, label: "First observation" }],
    reviews: [],
  },
  {
    id: "MS-1051",
    listing: {
      id: "LIST-1051",
      site: "Demo Pharmacy B",
      sourceUrl: "https://demo-b.example/listings/demo-atorva-10-capsule",
      productName: "Demo Atorva-10 Capsule",
      compositionRaw: "Atorvastatin 10 mg",
      packSizeRaw: "1 strip",
      mrp: 68,
      sellingPrice: 61.2,
      unitsInPack: null,
      observedAt: "2026-10-23T14:55:00+05:30",
      screenshot: svgDataUri("Demo Atorva-10 Capsule", "Atorvastatin 10 mg · 1 strip", 68, "Demo Pharmacy B"),
    },
    reference: references.capsule10,
    match: {
      id: "MATCH-1051",
      status: "uncertain",
      confidence: 61,
      parsedIngredient: "Atorvastatin",
      parsedStrength: "10 mg",
      parsedDosageForm: "Capsule",
      unitsInPack: null,
      fields: matchFields("Atorvastatin", "10 mg", "Capsule", null, references.capsule10),
      reasons: ["Pack text does not provide an integer unit count"],
    },
    status: "needs_verification",
    priorityParts: { discrepancy: 0, confidence: 14, evidence: 18, recurrence: 10 },
    isRecurrent: false,
    history: [],
    reviews: [],
  },
  {
    id: "MS-1038",
    listing: {
      id: "LIST-1038",
      site: "Demo Pharmacy A",
      sourceUrl: "https://demo-a.example/listings/demo-atorva-10-repeat",
      productName: "Demo Atorva-10 Repeat",
      compositionRaw: "Atorvastatin 10 mg",
      packSizeRaw: "Strip of 10 tablets",
      mrp: 78.5,
      sellingPrice: 70,
      unitsInPack: 10,
      observedAt: "2026-10-22T14:45:00+05:30",
      screenshot: svgDataUri("Demo Atorva-10 Repeat", "Atorvastatin 10 mg · 10 tablets", 78.5, "Demo Pharmacy A"),
    },
    reference: references.tablet10,
    match: matched("MATCH-1038", "10 mg", "Tablet", 10, references.tablet10, 97),
    status: "confirmed_for_review",
    priorityParts: { discrepancy: 27, confidence: 25, evidence: 15, recurrence: 10 },
    isRecurrent: true,
    history: [{ id: "OBS-1038-A", observedAt: "2026-10-22T14:45:00+05:30", mrp: 78.5, unitsInPack: 10, label: "First observation" }],
    reviews: [{ id: "REV-1038", action: "confirm", reviewer: "Demo Reviewer", note: "Demo review action", createdAt: "2026-10-22T16:00:00+05:30" }],
  },
  {
    id: "MS-1027",
    listing: {
      id: "LIST-1027",
      site: "Demo Pharmacy B",
      sourceUrl: "https://demo-b.example/listings/demo-atorva-5",
      productName: "Demo Atorva-5",
      compositionRaw: "Atorvastatin 5 mg",
      packSizeRaw: "Strip of 10 tablets",
      mrp: 38.9,
      sellingPrice: 35,
      unitsInPack: 10,
      observedAt: "2026-10-21T12:30:00+05:30",
      screenshot: svgDataUri("Demo Atorva-5", "Atorvastatin 5 mg · 10 tablets", 38.9, "Demo Pharmacy B"),
    },
    reference: references.tablet5,
    match: matched("MATCH-1027", "5 mg", "Tablet", 10, references.tablet5, 94),
    status: "dismissed",
    priorityParts: { discrepancy: 0, confidence: 10, evidence: 8, recurrence: 0 },
    isRecurrent: false,
    history: [{ id: "OBS-1027-A", observedAt: "2026-10-21T12:30:00+05:30", mrp: 38.9, unitsInPack: 10, label: "First observation" }],
    reviews: [{ id: "REV-1027", action: "dismiss", reviewer: "Demo Reviewer", note: "Within configured tolerance", createdAt: "2026-10-21T14:00:00+05:30" }],
  },
  {
    id: "MS-1053",
    listing: {
      id: "LIST-1053",
      site: "Demo Pharmacy C",
      sourceUrl: "https://demo-c.example/listings/demo-atorva-20",
      productName: "Demo Atorva-20",
      compositionRaw: "Atorvastatin 20 mg",
      packSizeRaw: "Strip of 10 tablets",
      mrp: 175,
      sellingPrice: 160,
      unitsInPack: 10,
      observedAt: "2026-10-23T16:20:00+05:30",
      screenshot: svgDataUri("Demo Atorva-20", "Atorvastatin 20 mg · 10 tablets", 175, "Demo Pharmacy C"),
    },
    reference: references.tablet20,
    match: matched("MATCH-1053", "20 mg", "Tablet", 10, references.tablet20, 95),
    status: "potential_discrepancy",
    priorityParts: { discrepancy: 23, confidence: 24, evidence: 17, recurrence: 5 },
    isRecurrent: false,
    history: [{ id: "OBS-1053-A", observedAt: "2026-10-23T16:20:00+05:30", mrp: 175, unitsInPack: 10, label: "First observation" }],
    reviews: [],
  },
];

export const MOCK_STATS: Stats = {
  generatedAt: "2026-10-24T10:42:00+05:30",
  sites: [
    { site: "Demo Pharmacy A", scanned: 8, matched: 7, needsVerification: 1 },
    { site: "Demo Pharmacy B", scanned: 8, matched: 6, needsVerification: 1 },
    { site: "Demo Pharmacy C", scanned: 8, matched: 6, needsVerification: 1 },
  ] satisfies SiteSummary[],
};

export const MOCK_SCAN = {
  medicines: ["Atorvastatin", "Paracetamol (preview)", "Amlodipine (preview)"],
  sites: ["Demo Pharmacy A", "Demo Pharmacy B", "Demo Pharmacy C"],
  stages: [
    { id: "discover", label: "Discover", detail: "Find product pages on selected demo sites" },
    { id: "extract", label: "Extract", detail: "Capture listing text, price, URL and screenshot" },
    { id: "match", label: "Match", detail: "Ingredient + strength + form must all agree" },
    { id: "calculate", label: "Calculate", detail: "MRP ÷ pack units vs ceiling + GST" },
    { id: "case_created", label: "Case created", detail: "Score evidence, discrepancy and recurrence" },
  ] satisfies ScanStage[],
};

const photoCase = MOCK_CASES[0];
export const MOCK_PHOTO_CHECK: PhotoCheck = {
  id: "PHOTO-DEMO-001",
  image: photoCase.listing.screenshot,
  listing: photoCase.listing,
  reference: photoCase.reference,
  fields: [
    { id: "product", label: "Product name", value: photoCase.listing.productName, confidence: 98 },
    { id: "ingredient", label: "Ingredient", value: photoCase.match.parsedIngredient ?? "", confidence: 99 },
    { id: "strength", label: "Strength", value: photoCase.match.parsedStrength ?? "", confidence: 97 },
    { id: "form", label: "Dosage form", value: photoCase.match.parsedDosageForm ?? "", confidence: 96 },
    { id: "pack", label: "Units in pack", value: String(photoCase.listing.unitsInPack ?? ""), confidence: 92 },
    { id: "mrp", label: "MRP (INR)", value: photoCase.listing.mrp.toFixed(2), confidence: 95 },
  ],
  status: "potential_discrepancy",
  imageQuality: "demo_not_evaluated",
};

export const MOCK_META = {
  label: "Demo data",
  updated: "24 Oct 2026, 10:42 IST",
  scope: "Atorvastatin · 3 fictional online pharmacies",
  notice: "Advisory triage only · Human verification required",
  referenceNotice: REFERENCE_SOURCE,
};
