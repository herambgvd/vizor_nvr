import ReactDOM from "react-dom/client";
import "@/index.css";
import App from "@/App";

const root = ReactDOM.createRoot(document.getElementById("root"));
// StrictMode removed — double-invokes effects, causes WebSocket connect
// loops and dev-only console noise. Re-enable for prod once all hooks
// are idempotent.
root.render(<App />);
