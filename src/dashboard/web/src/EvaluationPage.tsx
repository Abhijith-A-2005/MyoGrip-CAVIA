import { Header } from "./components/Header";
import { Panel } from "./components/Panel";
import type { Condition } from "./types/messages";
import "./EvaluationPage.css";

// Shell only: the content and data format of this page are decided after the pilot (team plan W4).

const CONDITIONS: Condition[] = ["C1_MANUAL", "C2_STATIC", "C3_ADAPTIVE"];
const SHORT: Record<Condition, string> = { C1_MANUAL: "Manual", C2_STATIC: "Static", C3_ADAPTIVE: "Adaptive" };

const METRICS = [
  { name: "EMG commands", how: "Gestures from menu shown to confirm" },
  { name: "Selection time", how: "Menu shown to confirming long flex" },
  { name: "Incorrect selections", how: "Confirmed grip differs from the task" },
  { name: "First-option acceptance", how: "Top item confirmed with no navigation" },
  { name: "Grasp success", how: "Marked by the experimenter per trial" },
  { name: "False activations", how: "Gestures during instructed rest" },
];

const QUESTIONNAIRES = [
  { name: "Workload", how: "NASA-TLX, raw" },
  { name: "Perceived control", how: "Likert, 7 points" },
  { name: "Confidence", how: "Likert, 7 points" },
  { name: "Ease of use", how: "System Usability Scale" },
];

function ResultTable({ rows }: { rows: { name: string; how: string }[] }) {
  return (
    <table className="rt">
      <thead>
        <tr>
          <th scope="col" className="rt-name">
            <span className="sr-only">Measure</span>
          </th>
          {CONDITIONS.map((c) => (
            <th key={c} scope="col" className="rt-cond" data-cond={c}>
              <span className="rt-swatch" />
              {SHORT[c]}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.name}>
            <th scope="row" className="rt-name">
              <span className="rt-metric">{r.name}</span>
              <span className="rt-how">{r.how}</span>
            </th>
            {CONDITIONS.map((c) => (
              <td key={c} className="rt-cell num">
                --
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Faint dashed sketches of the planned figures, so the layout of the results is visible now. */
const GHOSTS: { title: string; sketch: React.ReactNode }[] = [
  {
    title: "Selection time by condition",
    sketch: (
      <>
        {[40, 120, 200].map((x, i) => (
          <g key={x}>
            <line x1={x + 20} y1={18 + i * 6} x2={x + 20} y2={92 - i * 4} />
            <rect x={x} y={34 + i * 8} width="40" height={34 - i * 4} rx="3" />
          </g>
        ))}
      </>
    ),
  },
  {
    title: "EMG commands by condition",
    sketch: (
      <>
        {[
          [40, 22],
          [120, 46],
          [200, 64],
        ].map(([x, y]) => (
          <rect key={x} x={x} y={y} width="40" height={100 - y} rx="3" />
        ))}
      </>
    ),
  },
  {
    title: "Per-participant comparison",
    sketch: (
      <>
        {[30, 70, 110, 150, 190, 230].map((x, i) => (
          <g key={x}>
            <line x1={x} y1={30 + (i % 3) * 8} x2={x} y2={70 - (i % 2) * 10} />
            <circle cx={x} cy={30 + (i % 3) * 8} r="4" />
            <circle cx={x} cy={70 - (i % 2) * 10} r="4" />
          </g>
        ))}
      </>
    ),
  },
  {
    title: "Adaptation over trials",
    sketch: <polyline points="10,24 50,40 90,52 130,66 170,72 210,78 250,80" />,
  },
];

function Ghost({ title, sketch }: { title: string; sketch: React.ReactNode }) {
  return (
    <figure className="ghost">
      <svg viewBox="0 0 260 104" aria-hidden>
        <line className="ghost-axis" x1="4" y1="100" x2="256" y2="100" />
        <g className="ghost-marks">{sketch}</g>
      </svg>
      <figcaption>
        <span className="ghost-title">{title}</span>
        <span className="ghost-wait">Awaiting trials</span>
      </figcaption>
    </figure>
  );
}

export function EvaluationPage() {
  return (
    <div className="eval">
      <Header />

      <section className="eval-hero">
        <div>
          <h2 className="eval-title">Evaluation</h2>
          <p className="eval-lede">
            Results appear here after the trials. Every number is computed from the session logs, so it can be
            recomputed and checked.
          </p>
        </div>
        <blockquote className="eval-question">
          <p>
            Can preference-ranked, confidence-adaptive grip menus reduce EMG command burden and selection time
            without increasing incorrect choices or reducing perceived control?
          </p>
          <cite>Research question</cite>
        </blockquote>
      </section>

      <div className="eval-grid">
        <Panel area="eval-metrics" title="Interaction metrics" subtitle="Mean and standard deviation per condition">
          <ResultTable rows={METRICS} />
        </Panel>
        <Panel area="eval-questionnaires" title="Questionnaires" subtitle="After each condition block">
          <ResultTable rows={QUESTIONNAIRES} />
        </Panel>
        <Panel area="eval-analysis" title="Analysis" subtitle="Figures for the report">
          <div className="ghosts">
            {GHOSTS.map((g) => (
              <Ghost key={g.title} {...g} />
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}
