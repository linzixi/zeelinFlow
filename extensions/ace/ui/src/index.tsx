import { createRoot } from "react-dom/client";
import "@xyflow/react/dist/style.css";
import "./workbench.css";
import "./features/workbench/ace-canvas.css";
import App from "./features/workbench/App";
import type { HostContext } from "./lib/api";

export default {
  apiVersion: 1,
  module: "ace.v1",
  icon: "workflow",
  surfaces: [
    {
      id: "workbench",
      slot: "page",
      title: "ACE 工作台",
      mount(root: HTMLElement, context: HostContext) {
        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.crossOrigin = "use-credentials";
        link.href = new URL("./styles.css", import.meta.url).href;
        root.appendChild(link);
        const container = document.createElement("div");
        root.appendChild(container);
        const view = createRoot(container);
        view.render(<App host={context} />);
        return {
          dispose() {
            view.unmount();
            container.remove();
            link.remove();
          },
        };
      },
    },
  ],
};
