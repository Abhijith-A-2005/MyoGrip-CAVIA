import { useEffect, useState } from "react";
import { objectLabel, regionLabel } from "../labels";
import { isMock, videoUrl } from "../state/connect";
import { useDashboard } from "../state/store";
import type { Box, VisionState } from "../types/messages";
import "./CameraPanel.css";

// Overlay coordinates: a 4:3 viewBox matching the camera frame.
const VW = 1000;
const VH = 750;

const LOCK_TEXT: Record<VisionState, string> = {
  NO_OBJECT: "No object",
  SEARCHING: "Searching",
  LOCKED: "Locked",
  LOST: "Lost, hold steady",
};

function toRect(b: Box) {
  const x = b[0] * VW;
  const y = b[1] * VH;
  return { x, y, w: (b[2] - b[0]) * VW, h: (b[3] - b[1]) * VH };
}

/** Live wrist-camera feed with themed overlays drawn on top in SVG. */
export function CameraPanel({ focused }: { focused: boolean }) {
  const vision = useDashboard((s) => s.vision);
  const camera = useDashboard((s) => s.system?.camera);
  const link = useDashboard((s) => s.link);
  const [frameKey, setFrameKey] = useState(0);
  const [videoOk, setVideoOk] = useState(true);
  const src = videoUrl();

  const offline = link === "reconnecting" || link === "connecting";
  const stale = !offline && (camera?.status === "stale" || camera?.status === "down");
  // "down": no camera source at all; "stale": a stream that was live has stopped.
  const noCamera = camera?.status === "down";
  const state = vision?.state ?? "NO_OBJECT";
  const locked = state === "LOCKED";
  const box = vision?.box ? toRect(vision.box) : null;
  const region = vision?.region_box ? toRect(vision.region_box) : null;

  // MJPEG streams end on network errors. Retry every 2 s (never in a tight loop) while the video
  // is failing or the camera is stale, instead of showing a broken frame.
  const retrying = !isMock() && (stale || !videoOk);
  useEffect(() => {
    if (!retrying) return;
    const id = window.setInterval(() => setFrameKey((k) => k + 1), 2000);
    return () => window.clearInterval(id);
  }, [retrying]);

  return (
    <section className="cam" data-area="camera" data-focused={focused || undefined} aria-label="Wrist camera">
      {!stale && !offline && (
        <img
          key={frameKey}
          className="cam-feed"
          src={src}
          alt=""
          data-hidden={!videoOk || undefined}
          onLoad={() => setVideoOk(true)}
          onError={() => setVideoOk(false)}
        />
      )}
      {!videoOk && !stale && !offline && <p className="cam-novideo">Video not available yet</p>}
      <div className="cam-vignette" />

      <svg className="cam-overlay" viewBox={`0 0 ${VW} ${VH}`} aria-hidden>
        <FrameCorners />
        {box && !stale && !offline && (
          <g className="cam-object" data-locked={locked || undefined}>
            <rect x={box.x} y={box.y} width={box.w} height={box.h} rx={14} />
          </g>
        )}
        {region && !stale && !offline && (
          <g className="cam-region" data-locked={locked || undefined}>
            <rect x={region.x} y={region.y} width={region.w} height={region.h} rx={10} />
          </g>
        )}
        {!stale && !offline && <Reticle locked={locked} />}
      </svg>

      {box && vision?.object && !stale && !offline && (
        <span className="cam-tag cam-tag-object" style={{ left: `${(box.x / VW) * 100}%`, top: `${(box.y / VH) * 100}%` }}>
          {objectLabel(vision.object)} <span className="num">{Math.round(vision.det_conf * 100)}%</span>
        </span>
      )}
      {region && vision?.region && !stale && !offline && (
        <span
          className="cam-tag cam-tag-region"
          data-locked={locked || undefined}
          style={{ left: `${((region.x + region.w) / VW) * 100}%`, top: `${((region.y + region.h) / VH) * 100}%` }}
        >
          {regionLabel(vision.region)}
        </span>
      )}

      <div className="cam-hud cam-hud-top">
        <span className="cam-lock" data-state={state}>
          <span className="cam-lock-dot" />
          {LOCK_TEXT[state]}
        </span>
        {camera && !stale && !offline && (
          <span className="cam-stats num">
            {camera.source === "LAPTOP" ? "Laptop camera (dev), " : ""}
            {camera.fps.toFixed(1)} fps{camera.latency_ms > 0 ? `, ${camera.latency_ms} ms` : ""}
          </span>
        )}
      </div>

      {(stale || offline) && (
        <div className="cam-fault" role="status">
          <p className="cam-fault-title">
            {offline ? "Not connected to CAVIA" : noCamera ? "No camera connected" : "Camera stream lost"}
          </p>
          <p className="cam-fault-hint">
            {offline
              ? "Start the backend; this page reconnects by itself."
              : noCamera
                ? "Start vision with the wrist camera or the laptop camera."
                : "Reconnecting to the wrist camera…"}
          </p>
        </div>
      )}
    </section>
  );
}

function FrameCorners() {
  const L = 54;
  const m = 18;
  return (
    <g className="cam-corners">
      <path d={`M${m} ${m + L}V${m}H${m + L}`} />
      <path d={`M${VW - m - L} ${m}H${VW - m}V${m + L}`} />
      <path d={`M${VW - m} ${VH - m - L}V${VH - m}H${VW - m - L}`} />
      <path d={`M${m + L} ${VH - m}H${m}V${VH - m - L}`} />
    </g>
  );
}

/** Fixed centre reticle. The brackets close in when the region locks. */
function Reticle({ locked }: { locked: boolean }) {
  const cx = VW / 2;
  const cy = VH / 2;
  const r = 44;
  const l = 16;
  return (
    <g className="cam-reticle" data-locked={locked || undefined}>
      <path d={`M${cx - r} ${cy - r + l}V${cy - r}H${cx - r + l}`} />
      <path d={`M${cx + r - l} ${cy - r}H${cx + r}V${cy - r + l}`} />
      <path d={`M${cx + r} ${cy + r - l}V${cy + r}H${cx + r - l}`} />
      <path d={`M${cx - r + l} ${cy + r}H${cx - r}V${cy + r - l}`} />
      <circle cx={cx} cy={cy} r={3.5} />
    </g>
  );
}
