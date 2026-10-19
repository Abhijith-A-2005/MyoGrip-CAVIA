import { Panel } from "./components/Panel";
import "./LivePage.css";

export function LivePage() {
  return (
    <div className="live">
      <header className="live-header">
        <h1 className="wordmark">MyoGrip Cavia</h1>
      </header>

      <div className="live-top">
        <Panel area="camera" title="Camera" />
        <Panel area="context" title="Target" />
        <Panel area="hand" title="Hand" />
      </div>

      <div className="live-menus">
        <Panel area="adaptive" title="Adaptive menu" className="menu-adaptive" focused />
        <Panel area="full" title="Full menu" className="menu-full" />
      </div>

      <footer className="live-ribbon" aria-label="EMG events" />
    </div>
  );
}
