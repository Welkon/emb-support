import ReactDOM from "react-dom/client";
import { MotionConfig } from "framer-motion";
import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import App from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <MotionConfig reducedMotion="user"><App /></MotionConfig>,
);
