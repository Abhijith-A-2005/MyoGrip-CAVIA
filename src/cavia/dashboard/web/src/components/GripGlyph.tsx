import type { Grip } from "../types/messages";

/**
 * Contact diagrams: the grasped object (filled) and the fingers (thick strokes) pressing on it.
 * Clearer than hand drawings at small sizes, and consistent across the four grips.
 */
const SHAPES: Record<Grip, React.ReactNode> = {
  POWER: (
    <>
      <circle className="g-obj" cx="24" cy="24" r="8" />
      <path className="g-finger" d="M31.5 12.7A13.5 13.5 0 1 1 16.5 12.7" />
    </>
  ),
  PINCH: (
    <>
      <circle className="g-obj" cx="24" cy="24" r="3.2" />
      <path className="g-finger" d="M6 24h11M42 24H31" />
    </>
  ),
  TRIPOD: (
    <>
      <circle className="g-obj" cx="24" cy="24" r="3.2" />
      <path className="g-finger" d="M24 42V31M8.4 15l9.5 5.5M39.6 15l-9.5 5.5" />
    </>
  ),
  LATERAL: (
    <>
      <rect className="g-obj" x="9" y="21" width="30" height="5" rx="1.5" />
      <path className="g-finger" d="M24 7v8M8 33h32" />
    </>
  ),
};

export function GripGlyph({ grip, size = 48, className }: { grip: Grip; size?: number; className?: string }) {
  return (
    <svg
      className={`grip-glyph ${className ?? ""}`}
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      {SHAPES[grip]}
    </svg>
  );
}
