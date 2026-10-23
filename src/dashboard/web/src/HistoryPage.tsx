import { useEffect, useState } from "react";
import { GripGlyph } from "./components/GripGlyph";
import { Header } from "./components/Header";
import { Panel } from "./components/Panel";
import { ago, GRIP_LABEL, objectLabel, regionLabel } from "./labels";
import { fetchHistory } from "./state/connect";
import { useDashboard } from "./state/store";
import type { HistoryMsg, HistorySelection, MenuPolicy } from "./types/messages";
import "./HistoryPage.css";

const POLICY_SHORT: Record<MenuPolicy, string> = {
  ONE_CONFIRM: "One choice",
  TOP_TWO: "Top two",
  FULL_COMPATIBLE: "All that fit",
  FULL_MENU: "Full menu only",
};

const OUTCOME: Record<HistorySelection["status"], string> = {
  accepted: "Learned",
  cancelled: "Cancelled",
  pending: "Pending",
  failed: "Failed",
};

const pct = (n: number, of: number) => (of > 0 ? `${Math.round((n / of) * 100)}%` : "--");
const clock = (unix: number) => new Date(unix * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

function Stat({ label, value, note }: { label: string; value: string | number; note?: string }) {
  return (
    <div className="hs-stat">
      <span className="hs-stat-value num">{value}</span>
      <span className="hs-stat-label">{label}</span>
      {note && <span className="hs-stat-note">{note}</span>}
    </div>
  );
}

/** Learned grips grouped by object and region: the counts that rank the Adaptive menu. */
function Learned({ prefs }: { prefs: HistoryMsg["preferences"] }) {
  const groups = new Map<string, HistoryMsg["preferences"]>();
  for (const p of prefs) {
    const key = `${p.object}|${p.region}`;
    groups.set(key, [...(groups.get(key) ?? []), p]);
  }
  if (groups.size === 0) return <p className="hs-empty">Nothing learned yet. Grips held long enough on the Live page are learned here.</p>;
  return (
    <div className="hs-learned">
      {[...groups.values()].map((rows) => {
        const total = rows.reduce((a, r) => a + r.n, 0);
        return (
          <section key={`${rows[0].object}|${rows[0].region}`} className="hs-group">
            <h3 className="hs-group-title">
              {objectLabel(rows[0].object)} <span>{regionLabel(rows[0].region)}</span>
              <small className="num">{total === 1 ? "1 choice" : `${total} choices`}</small>
            </h3>
            {rows.map((r, i) => (
              <div key={r.grip} className="hs-pref" data-top={i === 0 || undefined}>
                <GripGlyph grip={r.grip} size={30} />
                <span className="hs-pref-name">{GRIP_LABEL[r.grip]}</span>
                <span className="hs-pref-bar">
                  <span style={{ transform: `scaleX(${r.n / total})` }} />
                </span>
                <span className="hs-pref-n num">
                  {r.n} <small>{pct(r.n, total)}</small>
                </span>
              </div>
            ))}
          </section>
        );
      })}
    </div>
  );
}

function source(s: HistorySelection): { text: string; note?: string } {
  if (s.menu === "adaptive") return { text: s.rank ? `Adaptive #${s.rank}` : "Adaptive" };
  return { text: "Full menu", note: s.compatible ? (s.items.includes(s.grip) ? undefined : "override") : "does not fit region" };
}

function Timeline({ rows, user }: { rows: HistorySelection[]; user: string }) {
  if (rows.length === 0) {
    return <p className="hs-empty">No selections yet for {user}. Confirm a grip on the Live page and it appears here.</p>;
  }
  return (
    <div className="hs-scroll">
      <table className="hs-table">
        <thead>
          <tr>
            <th scope="col">When</th>
            <th scope="col">Target</th>
            <th scope="col">Grip</th>
            <th scope="col">Chosen from</th>
            <th scope="col">Menu shown</th>
            <th scope="col">Outcome</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => {
            const from = source(s);
            return (
              <tr key={s.id}>
                <td>
                  <span className="hs-main">{ago(s.time)}</span>
                  <span className="hs-sub">{clock(s.time)}</span>
                </td>
                <td>
                  <span className="hs-main">{objectLabel(s.object)}</span>
                  <span className="hs-sub">{regionLabel(s.region) || "Unknown region"}</span>
                </td>
                <td>
                  <span className="hs-grip">
                    <GripGlyph grip={s.grip} size={26} />
                    {GRIP_LABEL[s.grip]}
                  </span>
                </td>
                <td>
                  <span className="hs-from" data-menu={s.menu}>{from.text}</span>
                  {from.note && <span className="hs-sub hs-warn">{from.note}</span>}
                </td>
                <td>
                  <span className="hs-main">{s.policy ? POLICY_SHORT[s.policy] : "--"}</span>
                  <span className="hs-sub">{s.items.map((g) => GRIP_LABEL[g]).join(", ")}</span>
                </td>
                <td>
                  <span className="hs-outcome" data-status={s.status}>{OUTCOME[s.status]}</span>
                  {s.grasp_success != null && (
                    <span className="hs-sub">{s.grasp_success ? "grasp held" : "grasp failed"}</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function HistoryPage() {
  const users = useDashboard((s) => s.users);
  const current = users?.current ?? "";
  const [picked, setPicked] = useState<string | null>(null);
  const viewing = picked ?? users?.current ?? "";
  const entry = users?.users.find((u) => u.user === viewing);
  const [data, setData] = useState<HistoryMsg | null>(null);
  const [error, setError] = useState("");

  // Refetch when the user changes or their counts change (a new selection was learned or cancelled).
  const version = `${viewing}|${entry?.selections ?? 0}|${entry?.accepted ?? 0}`;
  useEffect(() => {
    if (!viewing) return;
    const abort = new AbortController();
    fetchHistory(viewing, abort.signal)
      .then((h) => {
        setData(h);
        setError("");
      })
      .catch((err: unknown) => {
        if (!abort.signal.aborted) setError(err instanceof Error ? err.message : String(err));
      });
    return () => abort.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version]);

  const shown = data?.user === viewing ? data : null;
  const sum = shown?.summary;

  return (
    <div className="hist">
      <Header />

      <section className="hist-hero">
        <div className="hist-intro">
          <h2 className="hist-title">History</h2>
          <div className="hist-users" role="tablist" aria-label="User">
            {(users?.users ?? []).map((u) => (
              <button
                key={u.user}
                role="tab"
                aria-selected={u.user === viewing}
                className="hist-user"
                onClick={() => setPicked(u.user)}
              >
                {u.user}
                {u.user === current && <span className="hist-live">Live</span>}
              </button>
            ))}
          </div>
        </div>
        <div className="hist-stats">
          <Stat label="Selections" value={sum?.total ?? "--"} note={sum ? `${sum.cancelled} cancelled` : undefined} />
          <Stat label="Learned" value={sum?.accepted ?? "--"} note={sum ? `${pct(sum.accepted, sum.total)} of selections` : undefined} />
          <Stat label="From Adaptive menu" value={sum ? pct(sum.adaptive, sum.total) : "--"} note={sum ? `${sum.adaptive} of ${sum.total}` : undefined} />
          <Stat label="Top suggestion taken" value={sum ? pct(sum.first_option, sum.total) : "--"} note={sum ? `${sum.first_option} times` : undefined} />
          <Stat label="From Full menu" value={sum?.full ?? "--"} note="overrides of CAVIA" />
        </div>
      </section>

      <div className="hist-grid">
        <Panel area="hist-learned" title="What CAVIA has learned" subtitle="Learned grips per object and region. These counts rank the Adaptive menu">
          {shown ? <Learned prefs={shown.preferences} /> : <p className="hs-empty">{error || "Loading history"}</p>}
        </Panel>
        <Panel area="hist-timeline" title="Selections" subtitle={`Every confirmed grip for ${viewing || "this user"}, newest first`}>
          {shown ? <Timeline rows={shown.selections} user={viewing} /> : <p className="hs-empty">{error || "Loading history"}</p>}
        </Panel>
      </div>
    </div>
  );
}
