import { useEffect } from "react";
import { Atmosphere } from "./components/Atmosphere";
import { Stage } from "./components/Stage";
import { LivePage } from "./LivePage";
import { connect } from "./state/connect";

export default function App() {
  useEffect(() => connect().dispose, []);

  return (
    <Stage>
      <Atmosphere />
      <LivePage />
    </Stage>
  );
}
