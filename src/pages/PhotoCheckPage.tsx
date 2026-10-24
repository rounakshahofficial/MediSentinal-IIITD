import { useEffect, useRef, useState } from "react";
import { AlertCircle, Camera, RefreshCw, ShieldCheck, Trash2, Upload, VideoOff } from "lucide-react";
import { MOCK_PHOTO_CHECK } from "../data/mock";
import type { PhotoField } from "../types";
import { extractorClient } from "../api/extractor";
import { calculationView, formatCurrency, formatPercent, isPotentialDiscrepancy } from "../lib/calc";
import { preparePhoto, type PhotoQuality } from "../lib/photoQuality";
import { Card, ConfidenceBadge, DemoBadge, FocusButton } from "../components/ui";

export function PhotoCheckPage() {
  const [image, setImage] = useState<string | null>(MOCK_PHOTO_CHECK.image.trim());
  const [fields, setFields] = useState<PhotoField[]>(MOCK_PHOTO_CHECK.fields.map((field) => ({ ...field })));
  const [quality, setQuality] = useState<PhotoQuality | null>(null);
  const [photoError, setPhotoError] = useState<string | null>(null);
  const [processing, setProcessing] = useState(false);
  const [cameraOpen, setCameraOpen] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const objectUrl = useRef<string | null>(null);

  const revokePreview = () => {
    if (objectUrl.current) {
      URL.revokeObjectURL(objectUrl.current);
      objectUrl.current = null;
    }
  };

  const stopCamera = () => {
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
    if (video.current) video.current.srcObject = null;
    setCameraOpen(false);
  };

  useEffect(() => () => {
    stream.current?.getTracks().forEach((track) => track.stop());
    revokePreview();
  }, []);

  useEffect(() => {
    if (cameraOpen && video.current && stream.current) {
      video.current.srcObject = stream.current;
      void video.current.play().catch(() => setCameraError("Camera preview could not start."));
    }
  }, [cameraOpen]);

  const acceptPhoto = async (file: File) => {
    setProcessing(true);
    setPhotoError(null);
    try {
      const prepared = await preparePhoto(file);
      const extraction = await extractorClient.extract(prepared.blob);
      revokePreview();
      const nextUrl = URL.createObjectURL(prepared.blob);
      objectUrl.current = nextUrl;
      setImage(nextUrl);
      setQuality(prepared.quality);
      setFields(extraction.fields);
    } catch (error) {
      setPhotoError(error instanceof Error ? error.message : "The photo could not be processed.");
    } finally {
      setProcessing(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const startCamera = async () => {
    setCameraError(null);
    if (!navigator.mediaDevices?.getUserMedia) {
      setCameraError("Live camera is not supported in this browser. Use Take or upload photo instead.");
      return;
    }
    try {
      const nextStream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" } },
        audio: false,
      });
      stopCamera();
      stream.current = nextStream;
      setCameraOpen(true);
    } catch (error) {
      const denied = error instanceof DOMException && (error.name === "NotAllowedError" || error.name === "SecurityError");
      setCameraError(denied
        ? "Camera permission was denied. Allow camera access or use Take or upload photo."
        : "The live camera could not be opened. Use Take or upload photo instead.");
    }
  };

  const captureFrame = () => {
    const source = video.current;
    if (!source || source.videoWidth === 0 || source.videoHeight === 0) {
      setCameraError("Wait for the camera preview, then try again.");
      return;
    }
    const canvas = document.createElement("canvas");
    canvas.width = source.videoWidth;
    canvas.height = source.videoHeight;
    const context = canvas.getContext("2d");
    if (!context) {
      setCameraError("Camera capture is unavailable in this browser.");
      return;
    }
    context.drawImage(source, 0, 0);
    canvas.toBlob((blob) => {
      if (!blob) {
        setCameraError("The camera frame could not be captured.");
        return;
      }
      stopCamera();
      void acceptPhoto(new File([blob], "camera-capture.jpg", { type: "image/jpeg" }));
    }, "image/jpeg", 0.92);
  };

  const restoreDemo = () => {
    stopCamera();
    revokePreview();
    setImage(MOCK_PHOTO_CHECK.image.trim());
    setFields(MOCK_PHOTO_CHECK.fields.map((field) => ({ ...field })));
    setQuality(null);
    setPhotoError(null);
    setCameraError(null);
  };

  const deletePhoto = () => {
    stopCamera();
    revokePreview();
    setImage(null);
    setFields(MOCK_PHOTO_CHECK.fields.map((field) => ({ ...field, value: "" })));
    setQuality(null);
    setPhotoError(null);
    setCameraError(null);
  };

  const mrp = Number(fields.find((field) => field.id === "mrp")?.value ?? Number.NaN);
  const unitsValue = Number(fields.find((field) => field.id === "pack")?.value ?? Number.NaN);
  const units = Number.isFinite(unitsValue) && unitsValue > 0 ? unitsValue : null;
  const calc = calculationView(MOCK_PHOTO_CHECK.reference.ceilingPricePerUnit, MOCK_PHOTO_CHECK.reference.gstPercent, mrp, units);
  const flagged = isPotentialDiscrepancy(calc.observed, calc.allowed, 1);
  const needsRetake = quality?.isBlurry || quality?.isDark;

  return (
    <div className="space-y-6">
      <Card className="border-blue-100 bg-blue-50/50 p-4 text-sm text-blue-950">
        <div className="flex items-start gap-3"><ShieldCheck className="mt-0.5 h-5 w-5 shrink-0" /><div><strong>Photo privacy</strong><p className="mt-1 leading-6">The selected image is resized and checked in this browser. The current mock extractor does not upload it. Delete the photo when finished.</p><p className="mt-1 font-semibold">Checks price and label data only. Does not verify genuineness or safety.</p></div></div>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="p-4 sm:p-6">
          <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-base font-semibold">Pack photo</h2><p className="mt-1 text-sm text-slate-600">Photograph the front of one medicine pack in good light.</p></div><DemoBadge /></div>

          {cameraOpen ? <div className="relative mt-4 overflow-hidden rounded-xl bg-slate-950">
            <video ref={video} muted playsInline aria-label="Live camera preview" className="aspect-[4/3] w-full object-cover" />
            <div aria-hidden="true" className="pointer-events-none absolute inset-[10%] rounded-2xl border-2 border-dashed border-white/90 shadow-[0_0_0_999px_rgba(15,23,42,.38)]" />
            <p className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full bg-slate-950/75 px-3 py-1 text-xs font-semibold text-white">Fit the full label inside the guide</p>
          </div> : image ? <div className="mt-4 overflow-hidden rounded-xl border border-slate-200 bg-slate-100"><img src={image} alt="Medicine pack selected for photo check" className="aspect-[16/10] w-full object-contain" /></div> : <div className="mt-4 grid aspect-[16/10] place-items-center rounded-xl border-2 border-dashed border-slate-300 bg-slate-50 text-center text-sm text-slate-500"><div><Camera className="mx-auto mb-2 h-7 w-7" />No photo selected</div></div>}

          <input ref={fileInput} type="file" accept="image/*" capture="environment" className="sr-only" aria-label="Take or upload medicine pack photo" onChange={(event) => { const file = event.target.files?.[0]; if (file) void acceptPhoto(file); }} />
          <div className="mt-4 grid gap-2 sm:grid-cols-2">
            {cameraOpen ? <><FocusButton onClick={captureFrame} className="bg-blue-600 text-white hover:bg-blue-700"><Camera className="h-4 w-4" />Capture frame</FocusButton><FocusButton onClick={stopCamera} className="border border-slate-300 bg-white text-slate-800"><VideoOff className="h-4 w-4" />Close camera</FocusButton></> : <><FocusButton onClick={() => fileInput.current?.click()} disabled={processing} className="bg-blue-600 text-white hover:bg-blue-700"><Upload className="h-4 w-4" />{processing ? "Checking photo…" : "Take or upload photo"}</FocusButton><FocusButton onClick={() => void startCamera()} disabled={processing} className="border border-slate-300 bg-white text-slate-800 hover:bg-slate-50"><Camera className="h-4 w-4" />Open live camera</FocusButton></>}
            <FocusButton onClick={restoreDemo} className="border border-slate-300 bg-white text-slate-800"><RefreshCw className="h-4 w-4" />Restore demo</FocusButton><FocusButton onClick={deletePhoto} disabled={!image && !cameraOpen} className="border border-red-200 bg-white text-red-700"><Trash2 className="h-4 w-4" />Delete photo</FocusButton>
          </div>

          {cameraError && <p role="alert" className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">{cameraError}</p>}
          {photoError && <p role="alert" className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">{photoError}</p>}
          {quality && <div className={`mt-3 rounded-lg border p-3 text-sm ${needsRetake ? "border-amber-300 bg-amber-50 text-amber-950" : "border-green-200 bg-green-50 text-green-900"}`}><strong>{needsRetake ? `Retake: image looks ${quality.isBlurry && quality.isDark ? "blurry/dark" : quality.isBlurry ? "blurry" : "dark"}` : "Image quality checks passed"}</strong><p className="mt-1 font-mono text-xs">Blur score: {quality.blurScore.toFixed(1)} · Brightness: {quality.brightness.toFixed(1)} / 255</p></div>}
          <p className="mt-3 text-xs text-slate-500">Maximum 10 MB. Accepted photos are resized to at most 1600 px before extraction.</p>
        </Card>

        <Card className="p-4 sm:p-6">
          <div className="flex items-start justify-between gap-3"><div><h2 className="text-base font-semibold">Extracted fields</h2><p className="mt-1 text-sm text-slate-600">Mock-extracted values remain editable.</p></div><span className="rounded-full border border-green-200 bg-green-50 px-2.5 py-1 text-xs font-semibold text-green-800">Mock extractor</span></div>
          <div className="mt-5 grid gap-4 sm:grid-cols-2">{fields.map((field, index) => <label key={field.id} className="block"><span className="flex min-h-6 flex-wrap items-center justify-between gap-1 text-xs font-semibold text-slate-700"><span>{field.label}</span><ConfidenceBadge value={field.confidence} /></span><input value={field.value} onChange={(event) => setFields((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, value: event.target.value } : item))} className="mt-2 h-11 w-full rounded-lg border border-slate-300 px-3 text-sm focus:border-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-200" /></label>)}</div>
        </Card>
      </div>

      <Card className={flagged ? "border-red-200 p-5 sm:p-6" : "border-amber-200 p-5 sm:p-6"}>
        <div className="flex flex-col gap-5 md:flex-row md:items-center md:justify-between"><div className="flex items-start gap-3"><span className={flagged ? "grid h-10 w-10 shrink-0 place-items-center rounded-full bg-red-50 text-red-700" : "grid h-10 w-10 shrink-0 place-items-center rounded-full bg-amber-50 text-amber-800"}><AlertCircle className="h-5 w-5" /></span><div><h2 className="text-base font-semibold">Photo check result · {flagged ? "Potential discrepancy" : "Needs verification"}</h2><p className="mt-2 text-sm text-slate-600">Observed <strong>{formatCurrency(calc.observed)} / unit</strong> vs allowed <strong>{formatCurrency(calc.allowed)} / unit</strong>.</p><p className="mt-2 max-w-4xl font-mono text-xs leading-5 text-slate-600">{calc.discrepancyFormula}</p></div></div><div className="shrink-0"><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Potential difference</p><p className={flagged ? "mt-1 text-2xl font-bold text-red-700" : "mt-1 text-2xl font-bold text-amber-800"}>{formatPercent(calc.discrepancy)}</p></div></div>
      </Card>
    </div>
  );
}
