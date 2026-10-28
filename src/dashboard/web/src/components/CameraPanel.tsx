import { useEffect, useState } from "react";
import { objectLabel, regionLabel } from "../labels";
import { isMock, videoUrl } from "../state/connect";
import { useDashboard } from "../state/store";
import { frameFit, reticleGeometry } from "../state/targeting";
import type { Box, Targeting, VisionState } from "../types/messages";
import "./CameraPanel.css";

// Overlay coordinates: a 4:3 viewBox matching the camera frame.
const VW = 1000;
const VH = 750;
// The wider 16:9 viewfinder contains the full source frame. Corners outline the panel.
const CW = 1000;
const CH = 562.5;
// Labels sit above the object box and below the region box; keep both inside the visible band (% of frame height).
const TAG_MIN_TOP = 5;
const TAG_MAX_TOP = 95;

const LOCK_TEXT: Record<VisionState, string> = {
  NO_OBJECT: "No object",
  SEARCHING: "Searching",
  LOCKED: "Locked",
  LOST: "Lost, hold steady",
};

function toRect(b: Box, width: number, height: number) {
  const x = b[0] * width;
  const y = b[1] * height;
  return { x, y, w: (b[2] - b[0]) * width, h: (b[3] - b[1]) * height };
}

/** Live wrist-camera feed with themed overlays drawn on top in SVG. */
export function CameraPanel({ focused }: { focused: boolean }) {
  const vision = useDashboard((s) => s.vision);
  const camera = useDashboard((s) => s.system?.camera);
  const link = useDashboard((s) => s.link);
  const paused = useDashboard(
    (s) => s.system?.vision.status === "paused"
  );
  const [frameKey, setFrameKey] = useState(0);
  const [videoOk, setVideoOk] = useState(true);
  const src = videoUrl();

  const offline = link === "reconnecting" || link === "connecting";
  const stale = !offline && (camera?.status === "stale" || camera?.status === "down");
  // "down": no camera source at all; "stale": a stream that was live has stopped.
  const noCamera = camera?.status === "down";
  const state = vision?.state ?? "NO_OBJECT";
  const locked = state === "LOCKED";
  const targeting = vision?.targeting;
  const [vw, vh] = targeting?.frame_size ?? [VW, VH];
  const stageText = targeting ? {
    object: "Stage 1: object",
    settling: "Object locked: settling",
    region: "Stage 2: region",
  }[targeting.stage] : null;
  const box = !paused && videoOk && vision?.box
    ? toRect(vision.box, vw, vh)
    : null;

  const region = !paused && videoOk && vision?.region_box
    ? toRect(vision.region_box, vw, vh)
    : null;

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
      {/* Fit the whole source frame so the large circle is never cropped or stretched. */}
      <div className="cam-frame" style={frameFit(vw, vh)}>
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
        <div className="cam-vignette" />

        <svg className="cam-overlay" viewBox={`0 0 ${vw} ${vh}`} aria-hidden>
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
          {!stale && !offline && !paused && videoOk && (
            <Reticle targeting={targeting} width={vw} height={vh} />
          )}
        </svg>

        {box && vision?.object && !stale && !offline && (
          <span className="cam-tag cam-tag-object" style={{ left: `${(box.x / vw) * 100}%`, top: `${Math.max(TAG_MIN_TOP, (box.y / vh) * 100)}%` }}>
            {objectLabel(vision.object)} <span className="num">{Math.round(vision.det_conf * 100)}%</span>
          </span>
        )}
        {region && vision?.region && !stale && !offline && (
          <span
            className="cam-tag cam-tag-region"
            data-locked={locked || undefined}
            style={{
              left: `${((region.x + region.w) / vw) * 100}%`,
              top: `${Math.min(TAG_MAX_TOP, ((region.y + region.h) / vh) * 100)}%`,
            }}
          >
            {regionLabel(vision.region)}
          </span>
        )}
      </div>

      {!videoOk && !stale && !offline && <p className="cam-novideo">Video not available yet</p>}
      <svg className="cam-overlay" viewBox={`0 0 ${CW} ${CH}`} aria-hidden>
        <FrameCorners />
      </svg>

      <div className="cam-hud cam-hud-top">
        <span className="cam-lock" data-state={state}>
          <span className="cam-lock-dot" />
          {paused ? "Detection paused until HOME" : `${stageText ? `${stageText} · ` : ""}${LOCK_TEXT[state]}`}
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
      <path d={`M${CW - m - L} ${m}H${CW - m}V${m + L}`} />
      <path d={`M${CW - m} ${CH - m - L}V${CH - m}H${CW - m - L}`} />
      <path d={`M${m + L} ${CH - m}H${m}V${CH - m - L}`} />
    </g>
  );
}

/** Pixel geometry comes from the same frame used for object/region hit-testing. */
function Reticle({ targeting, width, height }: {
  targeting?: Targeting | null; width: number; height: number;
}) {
  const { cx, cy, radius, path, stage } = reticleGeometry(targeting, width, height);
  return (
    <g className="cam-reticle" data-stage={stage}>
      {radius !== null ? <circle cx={cx} cy={cy} r={radius} /> : (
        <path d={path} />
      )}
    </g>
  );
}
