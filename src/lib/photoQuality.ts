export const MAX_PHOTO_BYTES = 10 * 1024 * 1024;
export const MAX_PHOTO_DIMENSION = 1600;
export const BLUR_THRESHOLD = 100;
export const DARK_THRESHOLD = 55;

export interface PhotoQuality {
  blurScore: number;
  brightness: number;
  isBlurry: boolean;
  isDark: boolean;
}

export interface PreparedPhoto {
  blob: Blob;
  width: number;
  height: number;
  quality: PhotoQuality;
}

export function averageBrightness(grayscale: Uint8ClampedArray): number {
  if (grayscale.length === 0) return 0;
  return grayscale.reduce((total, value) => total + value, 0) / grayscale.length;
}

export function varianceOfLaplacian(
  grayscale: Uint8ClampedArray,
  width: number,
  height: number,
): number {
  if (width < 3 || height < 3 || grayscale.length !== width * height) return 0;
  const values: number[] = [];
  for (let y = 1; y < height - 1; y += 1) {
    for (let x = 1; x < width - 1; x += 1) {
      const index = y * width + x;
      values.push(
        grayscale[index - width]
        + grayscale[index - 1]
        - 4 * grayscale[index]
        + grayscale[index + 1]
        + grayscale[index + width],
      );
    }
  }
  if (values.length === 0) return 0;
  const mean = values.reduce((total, value) => total + value, 0) / values.length;
  return values.reduce((total, value) => total + (value - mean) ** 2, 0) / values.length;
}

export function qualityFromGrayscale(
  grayscale: Uint8ClampedArray,
  width: number,
  height: number,
  blurThreshold = BLUR_THRESHOLD,
  darkThreshold = DARK_THRESHOLD,
): PhotoQuality {
  const blurScore = varianceOfLaplacian(grayscale, width, height);
  const brightness = averageBrightness(grayscale);
  return {
    blurScore,
    brightness,
    isBlurry: blurScore < blurThreshold,
    isDark: brightness < darkThreshold,
  };
}

function imageDataToGrayscale(imageData: ImageData): Uint8ClampedArray {
  const grayscale = new Uint8ClampedArray(imageData.width * imageData.height);
  for (let source = 0, target = 0; source < imageData.data.length; source += 4, target += 1) {
    grayscale[target] = Math.round(
      imageData.data[source] * 0.299
      + imageData.data[source + 1] * 0.587
      + imageData.data[source + 2] * 0.114,
    );
  }
  return grayscale;
}

function canvasBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error("Could not encode the resized photo")), "image/jpeg", 0.9);
  });
}

function loadImage(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const objectUrl = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => {
      URL.revokeObjectURL(objectUrl);
      resolve(image);
    };
    image.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      reject(new Error("The selected file is not a readable image"));
    };
    image.src = objectUrl;
  });
}

export async function preparePhoto(file: File): Promise<PreparedPhoto> {
  if (!file.type.startsWith("image/")) throw new Error("Choose an image file");
  if (file.size > MAX_PHOTO_BYTES) throw new Error("Photo must be 10 MB or smaller");

  const image = await loadImage(file);
  const scale = Math.min(1, MAX_PHOTO_DIMENSION / Math.max(image.naturalWidth, image.naturalHeight));
  const width = Math.max(1, Math.round(image.naturalWidth * scale));
  const height = Math.max(1, Math.round(image.naturalHeight * scale));
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) throw new Error("Image checks are unavailable in this browser");
  context.drawImage(image, 0, 0, width, height);

  const checkScale = Math.min(1, 320 / Math.max(width, height));
  const checkWidth = Math.max(1, Math.round(width * checkScale));
  const checkHeight = Math.max(1, Math.round(height * checkScale));
  const checkCanvas = document.createElement("canvas");
  checkCanvas.width = checkWidth;
  checkCanvas.height = checkHeight;
  const checkContext = checkCanvas.getContext("2d", { willReadFrequently: true });
  if (!checkContext) throw new Error("Image checks are unavailable in this browser");
  checkContext.drawImage(canvas, 0, 0, checkWidth, checkHeight);
  const imageData = checkContext.getImageData(0, 0, checkWidth, checkHeight);

  return {
    blob: await canvasBlob(canvas),
    width,
    height,
    quality: qualityFromGrayscale(imageDataToGrayscale(imageData), checkWidth, checkHeight),
  };
}
