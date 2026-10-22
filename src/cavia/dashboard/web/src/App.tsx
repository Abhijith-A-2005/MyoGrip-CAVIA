import { useEffect } from "react";
import { Atmosphere } from "./components/Atmosphere";
import { ExperimenterDrawer } from "./components/ExperimenterDrawer";
import { Stage } from "./components/Stage";
import { EvaluationPage } from "./EvaluationPage";
import { LivePage } from "./LivePage";
import { connect } from "./state/connect";
import { useDrawerShortcut, useRoute } from "./state/ui";

export default function App() {
  const route = useRoute();
  useEffect(() => connect().dispose, []);
  useDrawerShortcut();

  return (
    <Stage>
      <Atmosphere />
      {route === "evaluation" ? <EvaluationPage /> : <LivePage />}
      <ExperimenterDrawer />
    </Stage>
  );
}
