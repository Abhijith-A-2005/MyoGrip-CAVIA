import { FocusLight } from "./components/FocusLight";
import { Header } from "./components/Header";
import { Panel } from "./components/Panel";
import { focusArea, POLICY_SUBTITLE } from "./labels";
import { useDashboard } from "./state/store";
import "./LivePage.css";

export function LivePage() {
  const fsm = useDashboard((s) => s.fsm);
  const menu = useDashboard((s) => s.menu);
  const focus = focusArea(fsm);
  const actuating = focus === "hand";

  return (
    <div className="live" data-focus={focus}>
      <FocusLight area={focus} />
      <Header />

      <div className="live-top">
        <Panel area="camera" title="Wrist camera" focused={focus === "camera"} />
        <Panel area="context" title="Target" />
        <Panel area="hand" title="Hand" focused={actuating} />
      </div>

      <div className="live-menus">
        <Panel
          area="adaptive"
          title="Adaptive menu"
          subtitle={menu ? POLICY_SUBTITLE[menu.policy] : "Point the reticle at an object to get suggestions"}
          className="menu-adaptive"
          focused={focus === "adaptive"}
          dimmed={focus === "full" || (actuating && fsm?.menu_kind !== "ADAPTIVE")}
        />
        <Panel
          area="full"
          title="Full menu"
          subtitle="All calibrated grips"
          className="menu-full"
          focused={focus === "full"}
          dimmed={focus === "adaptive" || (actuating && fsm?.menu_kind !== "FULL")}
        />
      </div>

      <footer className="live-ribbon" aria-label="EMG events" />
    </div>
  );
}
