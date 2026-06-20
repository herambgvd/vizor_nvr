// =============================================================================
// TwoFactorCard — self-service two-factor authentication (TOTP) management.
//
// Renders inside the Settings → Security tab. Three states:
//   - disabled  → "Enable" button starts the setup flow
//   - setup     → show the secret for the authenticator app + verify a code
//   - enabled   → show status + a guarded "Turn off" flow
//
// Recovery codes are shown exactly once after enabling — the operator must
// save them. They are never retrievable again.
// =============================================================================

import React, { useState } from "react";
import { ShieldCheck, ShieldOff, KeyRound, Copy, Check } from "lucide-react";
import { toast } from "sonner";

import { useAuth } from "../../context/AuthContext";
import { enable2FA, verify2FA, disable2FA } from "../../api/system";
import { friendlyError } from "../../lib/utils";

const fieldStyle = {
  background: "var(--console-raised)",
  border: "1px solid var(--console-border)",
  color: "var(--console-text)",
};

const Input = (props) => (
  <input
    {...props}
    className="w-full rounded font-telemetry text-xs h-[30px] px-2 border outline-none focus:ring-1"
    style={{ ...fieldStyle, "--tw-ring-color": "var(--console-accent)" }}
  />
);

const PrimaryButton = ({ children, disabled, onClick, type = "button" }) => (
  <button
    type={type}
    onClick={onClick}
    disabled={disabled}
    className="inline-flex items-center h-[30px] px-4 rounded font-telemetry text-xs font-semibold uppercase tracking-wide transition-opacity disabled:opacity-50"
    style={{ background: "var(--console-accent)", color: "var(--console-accent-foreground)" }}
  >
    {children}
  </button>
);

const GhostButton = ({ children, disabled, onClick, danger }) => (
  <button
    type="button"
    onClick={onClick}
    disabled={disabled}
    className="inline-flex items-center h-[30px] px-4 rounded font-telemetry text-xs font-semibold uppercase tracking-wide border transition-colors hover:bg-white/5 disabled:opacity-50"
    style={{
      borderColor: danger ? "var(--console-rec)" : "var(--console-border)",
      color: danger ? "var(--console-rec)" : "var(--console-text)",
      background: "transparent",
    }}
  >
    {children}
  </button>
);

const TwoFactorCard = () => {
  const { user, refreshUser } = useAuth();
  const enabled = user?.totp_enabled === true;

  // setup flow
  const [setup, setSetup] = useState(null); // { secret, otpauth_uri }
  const [verifyToken, setVerifyToken] = useState("");
  const [recoveryCodes, setRecoveryCodes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  // disable flow
  const [disabling, setDisabling] = useState(false);
  const [disableToken, setDisableToken] = useState("");

  const startSetup = async () => {
    setBusy(true);
    try {
      const data = await enable2FA();
      setSetup(data);
      setVerifyToken("");
      setRecoveryCodes(null);
    } catch (err) {
      toast.error(friendlyError(err, "Couldn't start two-factor setup."));
    } finally {
      setBusy(false);
    }
  };

  const confirmSetup = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const res = await verify2FA(verifyToken.trim());
      setRecoveryCodes(res.recovery_codes || []);
      setSetup(null);
      setVerifyToken("");
      await refreshUser();
      toast.success("Two-factor authentication is on");
    } catch (err) {
      // 400 from this endpoint means the code didn't match — give a clear hint
      // rather than the generic permission message.
      const msg =
        err?.response?.status === 400
          ? "That code wasn't valid. Check your authenticator app and try again."
          : friendlyError(err, "Couldn't verify the code.");
      toast.error(msg);
    } finally {
      setBusy(false);
    }
  };

  const confirmDisable = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await disable2FA(disableToken.trim());
      setDisabling(false);
      setDisableToken("");
      await refreshUser();
      toast.success("Two-factor authentication is off");
    } catch (err) {
      const msg =
        err?.response?.status === 400
          ? "That code wasn't valid. Enter a current code or a recovery code."
          : friendlyError(err, "Couldn't turn off two-factor authentication.");
      toast.error(msg);
    } finally {
      setBusy(false);
    }
  };

  const copySecret = () => {
    if (!setup?.secret) return;
    navigator.clipboard?.writeText(setup.secret).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      },
      () => toast.error("Couldn't copy. Select and copy the code manually."),
    );
  };

  // ── Recovery codes just generated — show once ──────────────────────────
  if (recoveryCodes) {
    return (
      <div className="space-y-3">
        <div
          className="rounded p-3 font-telemetry text-xs"
          style={{ background: "rgba(245,158,11,0.1)", border: "1px solid rgba(245,158,11,0.3)", color: "var(--console-alarm)" }}
        >
          Save these recovery codes now. Each can be used once to sign in if you
          lose your authenticator. They will not be shown again.
        </div>
        <div
          className="grid grid-cols-2 gap-2 rounded p-3"
          style={fieldStyle}
        >
          {recoveryCodes.map((c) => (
            <code key={c} className="font-mono text-sm tracking-wide" style={{ color: "var(--console-text)" }}>
              {c}
            </code>
          ))}
        </div>
        <div className="flex gap-2">
          <GhostButton
            onClick={() => {
              navigator.clipboard?.writeText(recoveryCodes.join("\n"));
              toast.success("Recovery codes copied");
            }}
          >
            <Copy className="h-3.5 w-3.5 mr-1.5" />
            Copy codes
          </GhostButton>
          <PrimaryButton onClick={() => setRecoveryCodes(null)}>
            <Check className="h-3.5 w-3.5 mr-1.5" />
            I've saved them
          </PrimaryButton>
        </div>
      </div>
    );
  }

  // ── Setup in progress — show secret + verify ───────────────────────────
  if (setup) {
    return (
      <form onSubmit={confirmSetup} className="space-y-4">
        <p className="font-telemetry text-xs leading-relaxed" style={{ color: "var(--console-muted)" }}>
          In your authenticator app (Google Authenticator, 1Password, Authy…),
          add an account and enter this setup key, then type the 6-digit code it
          shows to confirm.
        </p>
        <div>
          <label className="block font-telemetry text-[11px] uppercase tracking-wide mb-1" style={{ color: "var(--console-muted)" }}>
            Setup key
          </label>
          <div className="flex items-center gap-2">
            <code
              className="flex-1 rounded px-3 py-2 font-mono text-sm tracking-[0.15em] break-all"
              style={fieldStyle}
            >
              {setup.secret}
            </code>
            <GhostButton onClick={copySecret}>
              {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
            </GhostButton>
          </div>
        </div>
        <div>
          <label className="block font-telemetry text-[11px] uppercase tracking-wide mb-1" style={{ color: "var(--console-muted)" }}>
            6-digit code
          </label>
          <Input
            inputMode="numeric"
            autoComplete="one-time-code"
            placeholder="123456"
            value={verifyToken}
            onChange={(e) => setVerifyToken(e.target.value)}
            required
          />
        </div>
        <div className="flex gap-2">
          <GhostButton onClick={() => setSetup(null)} disabled={busy}>
            Cancel
          </GhostButton>
          <PrimaryButton type="submit" disabled={busy || !verifyToken.trim()}>
            <ShieldCheck className="h-3.5 w-3.5 mr-1.5" />
            {busy ? "Verifying…" : "Verify & turn on"}
          </PrimaryButton>
        </div>
      </form>
    );
  }

  // ── Disable flow ───────────────────────────────────────────────────────
  if (disabling) {
    return (
      <form onSubmit={confirmDisable} className="space-y-4">
        <p className="font-telemetry text-xs leading-relaxed" style={{ color: "var(--console-muted)" }}>
          Enter a current authenticator code (or a recovery code) to turn off
          two-factor authentication.
        </p>
        <div>
          <label className="block font-telemetry text-[11px] uppercase tracking-wide mb-1" style={{ color: "var(--console-muted)" }}>
            Code
          </label>
          <Input
            autoComplete="one-time-code"
            placeholder="123456"
            value={disableToken}
            onChange={(e) => setDisableToken(e.target.value)}
            required
          />
        </div>
        <div className="flex gap-2">
          <GhostButton onClick={() => { setDisabling(false); setDisableToken(""); }} disabled={busy}>
            Cancel
          </GhostButton>
          <GhostButton type="submit" danger disabled={busy || !disableToken.trim()}>
            <ShieldOff className="h-3.5 w-3.5 mr-1.5" />
            {busy ? "Turning off…" : "Turn off"}
          </GhostButton>
        </div>
      </form>
    );
  }

  // ── Status (enabled / disabled) ────────────────────────────────────────
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        {enabled ? (
          <span
            className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded font-telemetry text-[11px] font-medium border"
            style={{ background: "rgba(20,184,166,0.12)", color: "var(--console-accent)", borderColor: "rgba(20,184,166,0.3)" }}
          >
            <ShieldCheck className="h-3.5 w-3.5" />
            Enabled
          </span>
        ) : (
          <span
            className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded font-telemetry text-[11px] font-medium border"
            style={{ background: "var(--console-raised)", color: "var(--console-muted)", borderColor: "var(--console-border)" }}
          >
            <ShieldOff className="h-3.5 w-3.5" />
            Off
          </span>
        )}
      </div>
      <p className="font-telemetry text-xs leading-relaxed" style={{ color: "var(--console-muted)" }}>
        {enabled
          ? "Your account asks for a one-time code from your authenticator app at sign-in."
          : "Add a second step at sign-in using an authenticator app for stronger account security."}
      </p>
      {enabled ? (
        <GhostButton danger onClick={() => setDisabling(true)}>
          <ShieldOff className="h-3.5 w-3.5 mr-1.5" />
          Turn off
        </GhostButton>
      ) : (
        <PrimaryButton onClick={startSetup} disabled={busy}>
          <KeyRound className="h-3.5 w-3.5 mr-1.5" />
          {busy ? "Starting…" : "Set up two-factor"}
        </PrimaryButton>
      )}
    </div>
  );
};

export default TwoFactorCard;
