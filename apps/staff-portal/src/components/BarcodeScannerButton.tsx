/**
 * BarcodeScannerButton — feature-detected, camera-driven barcode capture.
 *
 * Uses the browser's `BarcodeDetector` API (Chrome/Edge/Android) to read EAN
 * and Code-128 barcodes off a live camera stream. Falls back to a hidden
 * (no-op) state on Safari/Firefox where the API isn't shipped — staff can
 * still type the code by hand. We deliberately don't pull in a JS-side
 * polyfill (e.g. `quagga2`) until the iPad becomes a primary entry device,
 * since it adds ~50KB gzipped that the Mac shop floor doesn't need.
 *
 * Usage:
 *   <BarcodeScannerButton onDetected={(code) => setCode(code)} />
 *
 * The component shows a small camera-icon button. Clicking opens an in-page
 * overlay with the camera preview and a "stop" button. The first decoded
 * barcode fires `onDetected(code)` and closes the overlay.
 */
import { useEffect, useRef, useState } from "react";

// `BarcodeDetector` isn't in lib.dom.d.ts as of TS 5.4 — declare a minimal
// shape so we can type-check the call site without pulling in a separate
// .d.ts file.
type DetectedBarcode = { rawValue: string; format: string };
interface BarcodeDetectorLike {
  detect(source: CanvasImageSource): Promise<DetectedBarcode[]>;
}
interface BarcodeDetectorCtor {
  new (init?: { formats?: string[] }): BarcodeDetectorLike;
  getSupportedFormats?: () => Promise<string[]>;
}

function getDetectorCtor(): BarcodeDetectorCtor | null {
  if (typeof window === "undefined") return null;
  const ctor = (window as unknown as { BarcodeDetector?: BarcodeDetectorCtor })
    .BarcodeDetector;
  return ctor ?? null;
}

let didLogUnsupported = false;

export function isBarcodeScanSupported(): boolean {
  return getDetectorCtor() !== null;
}

export function BarcodeScannerButton({
  onDetected,
  disabled,
  title = "Scan barcode with camera",
}: {
  onDetected: (code: string) => void;
  disabled?: boolean;
  title?: string;
}) {
  const supported = isBarcodeScanSupported();
  const [open, setOpen] = useState(false);

  if (!supported) {
    if (!didLogUnsupported) {
      didLogUnsupported = true;
      console.info("BarcodeDetector is not supported in this browser; hiding camera scan button.");
    }
    return null;
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        disabled={disabled}
        title={title}
        className="rounded border border-gray-300 bg-white px-2 py-1 text-xs hover:bg-gray-50 disabled:opacity-60"
      >
        📷
      </button>
      {open && (
        <ScannerOverlay
          onCancel={() => setOpen(false)}
          onDetected={(code) => {
            setOpen(false);
            onDetected(code);
          }}
        />
      )}
    </>
  );
}

function ScannerOverlay({
  onCancel,
  onDetected,
}: {
  onCancel: () => void;
  onDetected: (code: string) => void;
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctor = getDetectorCtor();
    if (!ctor) {
      setError("Barcode scanning not supported in this browser.");
      return;
    }

    let stream: MediaStream | null = null;
    let cancelled = false;
    let rafId = 0;
    const detector = new ctor({
      formats: ["ean_13", "ean_8", "code_128", "code_39", "qr_code"],
    });

    const start = async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "environment" },
          audio: false,
        });
      } catch (err) {
        setError(
          err instanceof Error
            ? `Camera permission denied: ${err.message}`
            : "Camera permission denied.",
        );
        return;
      }
      if (cancelled) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      const v = videoRef.current;
      if (!v) return;
      v.srcObject = stream;
      try {
        await v.play();
      } catch {
        // Autoplay can be blocked; the stream still feeds detect().
      }
      const tick = async () => {
        if (cancelled || !videoRef.current) return;
        try {
          const hits = await detector.detect(videoRef.current);
          if (hits.length > 0 && hits[0].rawValue) {
            onDetected(hits[0].rawValue);
            return;
          }
        } catch {
          // Single-frame failures are normal (motion blur etc) — keep going.
        }
        rafId = window.requestAnimationFrame(tick);
      };
      rafId = window.requestAnimationFrame(tick);
    };

    void start();
    return () => {
      cancelled = true;
      if (rafId) window.cancelAnimationFrame(rafId);
      if (stream) stream.getTracks().forEach((t) => t.stop());
    };
  }, [onDetected]);

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/70 p-4">
      <div className="flex w-full max-w-md flex-col rounded-md bg-white p-3 shadow-xl">
        <div className="mb-2 flex items-center justify-between">
          <div className="text-sm font-semibold">Scan barcode</div>
          <button
            type="button"
            onClick={onCancel}
            className="text-xs text-gray-500 hover:underline"
          >
            Cancel
          </button>
        </div>
        {error ? (
          <div className="rounded border border-red-300 bg-red-50 p-2 text-xs text-red-800">
            {error}
          </div>
        ) : (
          <video
            ref={videoRef}
            playsInline
            muted
            className="aspect-[4/3] w-full rounded bg-black object-cover"
          />
        )}
        <div className="mt-2 text-[11px] text-gray-500">
          Point the camera at an EAN-13, Code-128 or QR barcode. Auto-fills the
          field as soon as it reads.
        </div>
      </div>
    </div>
  );
}
