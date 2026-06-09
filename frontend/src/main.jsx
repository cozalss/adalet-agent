import React from "react";
import ReactDOM from "react-dom/client";
import { Root } from "./Root.jsx";
import { ErrorBoundary } from "./components/ErrorBoundary.jsx";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ErrorBoundary>
      <Root />
    </ErrorBoundary>
  </React.StrictMode>,
);

// PWA: service worker kaydı (offline kabuk + kurulabilirlik).
// Yalnız production'da; dev'de HMR ile çakışmaması için atlanır.
if ("serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => { /* SW opsiyonel — başarısızlık akışı bozmaz */ });
  });
}
