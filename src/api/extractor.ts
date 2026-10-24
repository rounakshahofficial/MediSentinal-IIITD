import { MOCK_PHOTO_CHECK } from "../data/mock";
import type { PhotoField } from "../types";

export interface ExtractionResult {
  fields: PhotoField[];
  source: "mock" | "ocr";
}

export interface ExtractorClient {
  extract(image: Blob): Promise<ExtractionResult>;
}

export class MockExtractor implements ExtractorClient {
  async extract(_image: Blob): Promise<ExtractionResult> {
    return {
      fields: structuredClone(MOCK_PHOTO_CHECK.fields),
      source: "mock",
    };
  }
}

// Swap this instance for a backend ExtractorClient without changing the Photo Check UI.
export const extractorClient: ExtractorClient = new MockExtractor();
