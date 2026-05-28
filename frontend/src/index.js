import ReactDOM from "react-dom/client";
import "@/index.css";
import App from "@/App";

const root = ReactDOM.createRoot(document.getElementById("root"));
// StrictMode removed — double-invokes effects, causes WebSocket connect
// loops and dev-only console noise. Re-enable for prod once all hooks
// are idempotent.
root.render(<App />);

// Service Worker registration.
//
// Browsers require a trusted TLS cert for SW registration. With the
// self-signed cert that ships in the bootstrap image, Chrome rejects
// the registration ('SSL certificate error') and floods the console.
// We probe the SW script first with fetch() — if the browser refuses
// the script over TLS, we skip registration silently. Replace the
// cert (Let's Encrypt or operator-provided) and the SW will install
// on next load.
if ('serviceWorker' in navigator && process.env.NODE_ENV === 'production') {
  window.addEventListener('load', async () => {
    try {
      const probe = await fetch('/service-worker.js', { method: 'HEAD', cache: 'no-store' });
      if (!probe.ok) return;
      await navigator.serviceWorker.register('/service-worker.js');
    } catch (err) {
      // Self-signed / untrusted cert — log once at info level, not warn.
      console.info('Service worker not registered (untrusted TLS or fetch error). PWA install disabled.');
    }
  });
}
