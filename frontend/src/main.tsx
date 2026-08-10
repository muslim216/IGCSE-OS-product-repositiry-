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

const queryClient = new QueryClient();

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
