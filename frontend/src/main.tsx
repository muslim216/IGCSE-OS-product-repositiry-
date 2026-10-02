import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import { AuthProvider } from "./auth/AuthContext";
// Self-hosted webfonts. The CSP blocks external font hosts (font-src 'self'),
// so these are bundled by Vite as same-origin assets rather than loaded from a
// CDN. Lora carries the display/editorial voice, Inter the functional UI; the
// Lora italic axis backs the occasional serif-italic emphasis.
import "@fontsource-variable/inter/wght.css";
import "@fontsource-variable/lora/wght.css";
import "@fontsource-variable/lora/wght-italic.css";
import "./index.css";
import { shouldRetry } from "./lib/errors";

// The default retries every failure three times with backoff, so a bad link
// sat on "Loading…" for ~7s before saying it was not found. A 4xx will not
// change on retry.
const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: shouldRetry } },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
);
