"use client";

// Ana ekrandaki web uygulamasında QR okutma: iPhone'un kamera uygulaması QR adresini Safari'de
// açar, ana ekran uygulamasında değil. Bu yüzden uygulama içinden kamerayla okunur. Görüntü
// cihazda işlenir; hiçbir yere gönderilmez.

import { Camera, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

export function QrScanner({ onCode, onClose }: { onCode: (text: string) => void; onClose: () => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let stream: MediaStream | null = null;
    let frame = 0;
    let stopped = false;
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d", { willReadFrequently: true });

    (async () => {
      try {
        const { default: jsQR } = await import("jsqr");
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
        if (stopped || !video.current) return;
        video.current.srcObject = stream;
        await video.current.play();
        const scan = () => {
          if (stopped) return;
          const v = video.current;
          if (v && context && v.videoWidth > 0) {
            const scale = Math.min(1, 640 / v.videoWidth);
            canvas.width = Math.round(v.videoWidth * scale);
            canvas.height = Math.round(v.videoHeight * scale);
            context.drawImage(v, 0, 0, canvas.width, canvas.height);
            const image = context.getImageData(0, 0, canvas.width, canvas.height);
            const found = jsQR(image.data, image.width, image.height, { inversionAttempts: "dontInvert" });
            if (found?.data) {
              stopped = true;
              onCode(found.data);
              return;
            }
          }
          frame = requestAnimationFrame(scan);
        };
        frame = requestAnimationFrame(scan);
      } catch (e) {
        setError(
          e instanceof DOMException && e.name === "NotAllowedError"
            ? "Kamera izni verilmedi. Telefon Ayarları'ndan bu uygulamaya kamera izni verin."
            : "Kamera açılamadı.",
        );
      }
    })();
    return () => {
      stopped = true;
      cancelAnimationFrame(frame);
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, [onCode]);

  return (
    <div role="dialog" aria-modal="true" aria-labelledby="qr-baslik" className="fixed inset-0 z-40 flex flex-col bg-black" data-testid="phone-qr-scanner">
      <div className="flex items-center justify-between px-4 pb-3 pt-[max(env(safe-area-inset-top),16px)] text-white">
        <h2 id="qr-baslik" className="flex items-center gap-2 text-base font-semibold">
          <Camera size={18} aria-hidden="true" /> QR kodu okutun
        </h2>
        <button type="button" onClick={onClose} aria-label="Kapat" className="grid h-10 w-10 place-items-center rounded-2xl bg-white/10">
          <X size={20} aria-hidden="true" />
        </button>
      </div>
      <div className="relative flex-1 overflow-hidden">
        <video ref={video} playsInline muted className="absolute inset-0 h-full w-full object-cover" />
        <div className="pointer-events-none absolute inset-0 grid place-items-center" aria-hidden="true">
          <div className="h-64 w-64 rounded-3xl border-4 border-[#3be8ff] shadow-[0_0_0_9999px_rgba(0,0,0,0.45)]" />
        </div>
      </div>
      <p className="px-5 pb-[max(env(safe-area-inset-bottom),20px)] pt-4 text-center text-sm text-white/85">
        {error ?? "Bilgisayardaki uygulamada Telefon ekranında gösterilen QR kodunu çerçeveye getirin."}
      </p>
    </div>
  );
}
