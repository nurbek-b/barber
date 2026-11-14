import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { normalizeLang, translate } from "./i18n";
import "./index.css";
import { initTelegram } from "./telegram/sdk";

const root = createRoot(document.getElementById("root") as HTMLElement);

void initTelegram()
  .then((ok) => {
    if (ok) {
      root.render(
        <StrictMode>
          <App />
        </StrictMode>,
      );
      return;
    }
    root.render(
      <p className="p-8 text-center text-hint">
        {translate(normalizeLang(navigator.language), "error.outside")}
      </p>,
    );
  })
  .catch((error: unknown) => {
    console.error(error);
    root.render(<p className="p-8 text-center">{String(error)}</p>);
  });
