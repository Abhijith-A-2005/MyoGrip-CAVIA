import { useLayoutEffect, useRef, useState } from "react";
import { GRIP_HINT, GRIP_LABEL, movesText, movesToReach } from "../labels";
import type { FsmMsg, Grip, MenuMsg } from "../types/messages";
import { GripGlyph } from "./GripGlyph";
import "./Menus.css";

const ACTUATION = ["CLOSING", "HOLDING", "OPENING"];
const ROMAN = ["I", "II", "III", "IV", "V", "VI"];

type Pick = { selected: number; sealed: number };

/** Which row is selected (navigating) or sealed (confirmed, hand moving) in a given menu. */
function picks(fsm: FsmMsg | null, kind: "ADAPTIVE" | "FULL"): Pick {
  if (!fsm) return { selected: -1, sealed: -1 };
  if (fsm.state === kind) return { selected: fsm.selected_index, sealed: -1 };
  if (ACTUATION.includes(fsm.state) && fsm.menu_kind === kind) {
    return { selected: fsm.selected_index, sealed: fsm.selected_index };
  }
  return { selected: -1, sealed: -1 };
}

/** The highlight is one element that slides to the selected row (CSS transition on top/height). */
function useHighlight(index: number, deps: unknown[]) {
  const list = useRef<HTMLOListElement>(null);
  const [box, setBox] = useState<{ top: number; height: number } | null>(null);

  useLayoutEffect(() => {
    const row = index >= 0 ? (list.current?.children[index] as HTMLElement | undefined) : undefined;
    if (!row) {
      setBox(null);
      return;
    }
    const update = () => setBox({ top: row.offsetTop, height: row.offsetHeight });
    update();
    const ro = new ResizeObserver(update);
    ro.observe(row);
    return () => ro.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index, ...deps]);

  return { list, box };
}

function Highlight({ box, sealed, small }: { box: { top: number; height: number } | null; sealed: boolean; small?: boolean }) {
  return (
    <div
      className="mhl"
      data-small={small || undefined}
      data-sealed={sealed || undefined}
      data-visible={box ? true : undefined}
      style={box ? { top: box.top, height: box.height } : undefined}
    />
  );
}

function Lock() {
  return (
    <svg className="mrow-lock" viewBox="0 0 24 24" width="22" height="22" aria-hidden>
      <rect x="5" y="10.5" width="14" height="10" rx="2.5" />
      <path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5" />
    </svg>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="menu-empty">
      <svg viewBox="0 0 48 48" width="44" height="44" aria-hidden>
        <path d="M8 17V8h9M31 8h9v9M40 31v9h-9M17 40H8v-9" />
        <circle cx="24" cy="24" r="2.5" />
      </svg>
      <p>{text}</p>
    </div>
  );
}

export function AdaptiveMenu({ menu, fsm }: { menu: MenuMsg | null; fsm: FsmMsg | null }) {
  const { selected, sealed } = picks(fsm, "ADAPTIVE");
  const items = menu?.items ?? [];
  const { list, box } = useHighlight(selected, [items.join(), menu?.policy]);

  if (!menu) return <Empty text="Point the reticle at an object to get suggestions" />;
  if (menu.policy === "FULL_MENU" || items.length === 0) {
    return <Empty text="No suggestions in this condition. The user cycles through every calibrated grip." />;
  }

  const showShare = menu.condition !== "C2_STATIC";

  if (menu.policy === "ONE_CONFIRM") {
    const grip = items[0];
    const isSealed = sealed === 0;
    return (
      <div className="one" data-selected={selected === 0 || undefined} data-sealed={isSealed || undefined}>
        <GripGlyph grip={grip} size={96} className="one-glyph" />
        <div className="one-text">
          <p className="one-name">{GRIP_LABEL[grip]}</p>
          <p className="one-hint">
            {isSealed ? (
              <>
                <Lock /> Confirmed
              </>
            ) : (
              "Hold a long flex to confirm"
            )}
          </p>
        </div>
        <div className="one-share">
          <span className="one-share-pct num">{Math.round(menu.scores[0] * 100)}%</span>
          <span className="one-share-label">of your past choices for this region</span>
        </div>
      </div>
    );
  }

  return (
    <div className="menu-list-wrap">
      <Highlight box={box} sealed={sealed >= 0} />
      <ol className="mlist" ref={list} data-count={items.length}>
        {items.map((grip, i) => (
          <AdaptiveRow
            key={grip}
            grip={grip}
            rank={i}
            share={menu.scores[i]}
            showShare={showShare}
            moves={movesToReach(i, items.length)}
            selected={i === selected}
            sealed={i === sealed}
            muted={sealed >= 0 && i !== sealed}
          />
        ))}
      </ol>
    </div>
  );
}

function AdaptiveRow(props: {
  grip: Grip;
  rank: number;
  share: number;
  showShare: boolean;
  moves: number;
  selected: boolean;
  sealed: boolean;
  muted: boolean;
}) {
  const { grip, rank, share, showShare, moves, selected, sealed, muted } = props;
  const pct = Math.round(share * 100);
  return (
    <li
      className="mrow"
      data-selected={selected || undefined}
      data-sealed={sealed || undefined}
      data-muted={muted || undefined}
      aria-current={selected || undefined}
    >
      <span className="mrow-rank">{ROMAN[rank]}</span>
      <GripGlyph grip={grip} size={52} className="mrow-glyph" />
      <span className="mrow-text">
        <span className="mrow-name">{GRIP_LABEL[grip]}</span>
        <span className="mrow-hint">
          {sealed ? (
            <>
              <Lock /> Confirmed
            </>
          ) : (
            GRIP_HINT[grip]
          )}
        </span>
      </span>
      <span className="mrow-share">
        {showShare ? (
          <>
            <span className="mrow-share-track">
              <span className="mrow-share-fill" style={{ transform: `scaleX(${share})` }} />
            </span>
            <span className="mrow-share-pct num">{pct}%</span>
          </>
        ) : (
          <span className="mrow-share-note">Fits this region</span>
        )}
      </span>
      <span className="mrow-moves" data-ready={moves === 0 || undefined}>
        {movesText(moves)}
      </span>
    </li>
  );
}

export function FullMenu({ menu, fsm }: { menu: MenuMsg | null; fsm: FsmMsg | null }) {
  const { selected, sealed } = picks(fsm, "FULL");
  const items = menu?.full_menu ?? [];
  const { list, box } = useHighlight(selected, [items.join()]);

  if (!menu) return <Empty text="All calibrated grips appear here once a menu is open" />;

  const suggested = new Set(menu.items);
  return (
    <div className="menu-list-wrap">
      <Highlight box={box} sealed={sealed >= 0} small />
      <ol className="mlist mlist-full" ref={list}>
        {items.map((grip, i) => {
          const moves = movesToReach(i, items.length);
          const isSealed = i === sealed;
          return (
            <li
              key={grip}
              className="frow"
              data-selected={i === selected || undefined}
              data-sealed={isSealed || undefined}
              data-muted={(sealed >= 0 && !isSealed) || undefined}
              aria-current={i === selected || undefined}
            >
              <GripGlyph grip={grip} size={40} className="frow-glyph" />
              <span className="frow-name">{GRIP_LABEL[grip]}</span>
              <span className="frow-tags">
                {isSealed ? (
                  <span className="frow-confirmed">
                    <Lock /> Confirmed
                  </span>
                ) : (
                  suggested.has(grip) && <span className="frow-chip">Also suggested</span>
                )}
              </span>
              <span className="mrow-moves" data-ready={moves === 0 || undefined}>
                {movesText(moves)}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
