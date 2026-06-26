// =============================================================================
// Login Page - User Authentication
// =============================================================================
// Centered single-card auth on the dark console theme. Animated aurora +
// dot-grid backdrop, glowing brand mark, telemetry-style labels.
// =============================================================================

import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  Video,
  Eye,
  EyeOff,
  LogIn,
  UserPlus,
  ShieldCheck,
  KeyRound,
  ArrowLeft,
} from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { checkSetup } from "../api/auth";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "../components/ui/card";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "../components/ui/tabs";
import { toast } from "sonner";
import useBranding from "../hooks/useBranding";

const Login = () => {
  const navigate = useNavigate();
  const { login, register } = useAuth();
  const branding = useBranding();

  // Form states
  const [isLoading, setIsLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  // Two-factor step: when the account has 2FA enabled the backend rejects the
  // first request with a 2FA-required signal; we then show a code entry screen
  // and resubmit the same credentials with the TOTP / recovery code.
  const [twoFactorStep, setTwoFactorStep] = useState(false);
  const [totpToken, setTotpToken] = useState("");

  // Login form
  const [loginForm, setLoginForm] = useState({
    username: "",
    password: "",
  });

  // Register form
  const [registerForm, setRegisterForm] = useState({
    username: "",
    email: "",
    password: "",
    confirmPassword: "",
  });

  // null = loading, true = first-time setup, false = normal login
  const [setupRequired, setSetupRequired] = useState(null);

  useEffect(() => {
    checkSetup()
      .then((data) => setSetupRequired(data.required))
      .catch(() => setSetupRequired(false));
  }, []);

  /**
   * Map an auth error to a clean, operator-safe message. The backend's auth
   * detail strings are deliberately user-facing ("Invalid username or
   * password", "Account temporarily locked…"), so we surface them — but we
   * never render arrays/objects (422 internals) or server-fault detail.
   */
  const authErrorMessage = (error, fallback) => {
    const status = error?.response?.status;
    const detail = error?.response?.data?.detail;
    // Never leak validation internals or 5xx stack/fault text.
    if (Array.isArray(detail) || (detail && typeof detail === "object")) {
      return "Please check the details you entered and try again.";
    }
    if (status >= 500 || !error?.response) {
      return error?.response
        ? fallback
        : "Network problem — please check your connection and try again.";
    }
    return typeof detail === "string" && detail ? detail : fallback;
  };

  /**
   * Handle login form submission
   */
  const handleLogin = async (e) => {
    e.preventDefault();
    setIsLoading(true);

    try {
      await login(loginForm.username, loginForm.password, totpToken || undefined);
      toast.success("Welcome back!");
      resetTwoFactor();
      navigate("/");
    } catch (error) {
      const resp = error.response;
      // ── 2FA gate: backend signals a second factor is required ──────────
      if (
        resp?.status === 401 &&
        (resp.headers?.["x-2fa-required"] === "true" ||
          resp.data?.detail === "TOTP token required")
      ) {
        setTwoFactorStep(true);
        setIsLoading(false);
        return;
      }
      // Wrong/expired 2FA code while on the second step — keep the user there.
      if (twoFactorStep && resp?.data?.detail === "Invalid 2FA token") {
        toast.error("That code wasn't valid. Try again or use a recovery code.");
        setTotpToken("");
        setIsLoading(false);
        return;
      }
      // ── Forced / expired password change ───────────────────────────────
      if (
        resp?.status === 403 &&
        resp.headers?.["x-password-change-required"] === "true"
      ) {
        toast.error(
          authErrorMessage(
            error,
            "Your password must be changed before you can sign in. Please contact your administrator.",
          ),
        );
        resetTwoFactor();
        setIsLoading(false);
        return;
      }
      toast.error(
        authErrorMessage(error, "Couldn't sign you in. Please try again."),
      );
    } finally {
      setIsLoading(false);
    }
  };

  const resetTwoFactor = () => {
    setTwoFactorStep(false);
    setTotpToken("");
  };

  const cancelTwoFactor = () => {
    resetTwoFactor();
    setLoginForm((f) => ({ ...f, password: "" }));
  };

  /**
   * Handle registration form submission
   */
  const handleRegister = async (e) => {
    e.preventDefault();

    // Validate passwords match
    if (registerForm.password !== registerForm.confirmPassword) {
      toast.error("Passwords do not match");
      return;
    }

    setIsLoading(true);

    try {
      await register(
        registerForm.username,
        registerForm.email,
        registerForm.password,
      );
      toast.success("Account created successfully!");
      navigate("/");
    } catch (error) {
      toast.error(
        authErrorMessage(
          error,
          "Couldn't create the account. Please try again.",
        ),
      );
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div
      className="relative min-h-screen flex items-center justify-center overflow-hidden px-4 py-10 text-foreground"
      style={{ background: "var(--console-bg)" }}
    >
      {/* Dot grid, faded toward center */}
      <div
        className="pointer-events-none absolute inset-0 z-0 opacity-[0.06]"
        style={{
          backgroundImage:
            "radial-gradient(circle at 1px 1px, rgba(255,255,255,0.7) 1px, transparent 0)",
          backgroundSize: "32px 32px",
          maskImage:
            "radial-gradient(ellipse 70% 55% at 50% 35%, #000 35%, transparent 100%)",
          WebkitMaskImage:
            "radial-gradient(ellipse 70% 55% at 50% 35%, #000 35%, transparent 100%)",
        }}
      />
      <div className="relative z-10 w-full max-w-md">
        {/* Brand */}
        <div className="flex flex-col items-center text-center mb-8">
          {branding.logo_url ? (
            <img
              src={branding.logo_url}
              alt={branding.system_name}
              className="h-14 w-14 rounded-2xl object-contain mb-4 shadow-[0_0_48px_rgba(20,184,166,0.35)]"
            />
          ) : (
            <div
              className="h-14 w-14 rounded-2xl flex items-center justify-center mb-4 shadow-[0_0_48px_rgba(20,184,166,0.5)]"
              style={{ backgroundColor: "var(--console-accent)" }}
            >
              <Video className="h-7 w-7 text-white" />
            </div>
          )}
          <h1 className="text-3xl font-semibold tracking-tight">
            <span style={{ color: "var(--console-text)" }}>{branding.system_name}</span>
          </h1>
          <p
            className="font-telemetry text-[11px] uppercase tracking-[0.2em] mt-2"
            style={{ color: "var(--console-muted)" }}
          >
            Network Video Recorder
          </p>
        </div>

        {/* Loading state */}
        {setupRequired === null && (
          <div className="flex items-center justify-center py-16">
            <div className="text-muted-foreground text-sm">
              Checking system status…
            </div>
          </div>
        )}

        {/* Two-factor code entry — shown after a correct password when the
            account has 2FA enabled. */}
        {twoFactorStep && (
          <Card
            className="border-[var(--console-border)] backdrop-blur-xl shadow-[0_0_70px_rgba(20,184,166,0.12)]"
            style={{ backgroundColor: "var(--console-panel)" }}
          >
            <CardHeader className="space-y-1">
              <CardTitle className="text-2xl tracking-tight flex items-center gap-2">
                <KeyRound
                  className="h-5 w-5"
                  style={{ color: "var(--console-accent)" }}
                />
                Two-factor verification
              </CardTitle>
              <CardDescription>
                Enter the 6-digit code from your authenticator app, or a recovery
                code.
              </CardDescription>
            </CardHeader>
            <form onSubmit={handleLogin}>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="login-totp">Authentication code</Label>
                  <Input
                    id="login-totp"
                    data-testid="login-totp-input"
                    inputMode="text"
                    autoComplete="one-time-code"
                    autoFocus
                    placeholder="123456"
                    value={totpToken}
                    onChange={(e) => setTotpToken(e.target.value.trim())}
                    required
                    disabled={isLoading}
                  />
                </div>
              </CardContent>
              <CardFooter className="flex flex-col gap-2">
                <Button
                  data-testid="login-totp-submit-btn"
                  type="submit"
                  className="w-full text-white border-0 hover:opacity-90 transition-opacity shadow-[0_0_30px_rgba(20,184,166,0.35)]"
                  style={{ backgroundColor: "var(--console-accent)" }}
                  disabled={isLoading || !totpToken}
                >
                  {isLoading ? "Verifying..." : "Verify & sign in"}
                </Button>
                <button
                  type="button"
                  onClick={cancelTwoFactor}
                  disabled={isLoading}
                  className="inline-flex items-center justify-center gap-1.5 text-sm text-muted-foreground hover:text-[var(--console-text)] disabled:opacity-50"
                >
                  <ArrowLeft className="h-3.5 w-3.5" />
                  Back to sign in
                </button>
              </CardFooter>
            </form>
          </Card>
        )}

        {/* Normal login — no register tab */}
        {!twoFactorStep && setupRequired === false && (
          <Card
            className="border-[var(--console-border)] backdrop-blur-xl shadow-[0_0_70px_rgba(20,184,166,0.12)]"
            style={{ backgroundColor: "var(--console-panel)" }}
          >
            <CardHeader className="space-y-1">
              <CardTitle className="text-2xl tracking-tight">
                Welcome back
              </CardTitle>
              <CardDescription>
                Enter your credentials to access your dashboard
              </CardDescription>
            </CardHeader>
            <form onSubmit={handleLogin}>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="solo-login-username">Username</Label>
                  <Input
                    id="solo-login-username"
                    data-testid="login-username-input"
                    placeholder="Enter your username"
                    value={loginForm.username}
                    onChange={(e) =>
                      setLoginForm({ ...loginForm, username: e.target.value })
                    }
                    required
                    disabled={isLoading}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="solo-login-password">Password</Label>
                  <div className="relative">
                    <Input
                      id="solo-login-password"
                      data-testid="login-password-input"
                      type={showPassword ? "text" : "password"}
                      placeholder="Enter your password"
                      value={loginForm.password}
                      onChange={(e) =>
                        setLoginForm({
                          ...loginForm,
                          password: e.target.value,
                        })
                      }
                      required
                      disabled={isLoading}
                    />
                    <button
                      type="button"
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-[var(--console-text)]"
                      onClick={() => setShowPassword(!showPassword)}
                    >
                      {showPassword ? (
                        <EyeOff className="h-4 w-4" />
                      ) : (
                        <Eye className="h-4 w-4" />
                      )}
                    </button>
                  </div>
                </div>
              </CardContent>
              <CardFooter>
                <Button
                  data-testid="login-submit-btn"
                  type="submit"
                  className="w-full text-white border-0 hover:opacity-90 transition-opacity shadow-[0_0_30px_rgba(20,184,166,0.35)]"
                  style={{ backgroundColor: "var(--console-accent)" }}
                  disabled={isLoading}
                >
                  {isLoading ? "Signing in..." : "Sign In"}
                </Button>
              </CardFooter>
            </form>
          </Card>
        )}

        {/* First-time setup — show both tabs, default to register */}
        {!twoFactorStep && setupRequired === true && (
          <Tabs defaultValue="register" className="w-full">
            <TabsList className="grid w-full grid-cols-2 mb-6">
              <TabsTrigger data-testid="login-tab" value="login" className="">
                <LogIn className="h-4 w-4 mr-2" />
                Login
              </TabsTrigger>
              <TabsTrigger
                data-testid="register-tab"
                value="register"
                className=""
              >
                <UserPlus className="h-4 w-4 mr-2" />
                Setup Admin
              </TabsTrigger>
            </TabsList>

            {/* Login Tab */}
            <TabsContent value="login">
              <Card
                className="border-[var(--console-border)] backdrop-blur-xl shadow-[0_0_70px_rgba(20,184,166,0.12)]"
                style={{ backgroundColor: "var(--console-panel)" }}
              >
                <CardHeader className="space-y-1">
                  <CardTitle className="text-2xl tracking-tight">
                    Welcome back
                  </CardTitle>
                  <CardDescription>
                    Enter your credentials to access your dashboard
                  </CardDescription>
                </CardHeader>
                <form onSubmit={handleLogin}>
                  <CardContent className="space-y-4">
                    <div className="space-y-2">
                      <Label htmlFor="login-username">Username</Label>
                      <Input
                        id="login-username"
                        data-testid="login-username-input"
                        placeholder="Enter your username"
                        value={loginForm.username}
                        onChange={(e) =>
                          setLoginForm({
                            ...loginForm,
                            username: e.target.value,
                          })
                        }
                        required
                        disabled={isLoading}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="login-password">Password</Label>
                      <div className="relative">
                        <Input
                          id="login-password"
                          data-testid="login-password-input"
                          type={showPassword ? "text" : "password"}
                          placeholder="Enter your password"
                          value={loginForm.password}
                          onChange={(e) =>
                            setLoginForm({
                              ...loginForm,
                              password: e.target.value,
                            })
                          }
                          required
                          disabled={isLoading}
                        />
                        <button
                          type="button"
                          className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-[var(--console-text)]"
                          onClick={() => setShowPassword(!showPassword)}
                        >
                          {showPassword ? (
                            <EyeOff className="h-4 w-4" />
                          ) : (
                            <Eye className="h-4 w-4" />
                          )}
                        </button>
                      </div>
                    </div>
                  </CardContent>
                  <CardFooter>
                    <Button
                      data-testid="login-submit-btn"
                      type="submit"
                      className="w-full text-white border-0 hover:opacity-90 transition-opacity shadow-[0_0_30px_rgba(20,184,166,0.35)]"
                      style={{ backgroundColor: "var(--console-accent)" }}
                      disabled={isLoading}
                    >
                      {isLoading ? "Signing in..." : "Sign In"}
                    </Button>
                  </CardFooter>
                </form>
              </Card>
            </TabsContent>

            {/* Register Tab */}
            <TabsContent value="register">
              <Card
                className="border-[var(--console-border)] backdrop-blur-xl shadow-[0_0_70px_rgba(20,184,166,0.12)]"
                style={{ backgroundColor: "var(--console-panel)" }}
              >
                <CardHeader className="space-y-1">
                  <CardTitle className="text-2xl tracking-tight">
                    Create administrator account
                  </CardTitle>
                  <CardDescription>
                    Set up the primary admin account for {branding.system_name}
                  </CardDescription>
                </CardHeader>
                <form onSubmit={handleRegister}>
                  <CardContent className="space-y-4">
                    <div className="space-y-2">
                      <Label htmlFor="register-username">Username</Label>
                      <Input
                        id="register-username"
                        data-testid="register-username-input"
                        placeholder="Choose a username"
                        value={registerForm.username}
                        onChange={(e) =>
                          setRegisterForm({
                            ...registerForm,
                            username: e.target.value,
                          })
                        }
                        required
                        disabled={isLoading}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="register-email">Email</Label>
                      <Input
                        id="register-email"
                        data-testid="register-email-input"
                        type="email"
                        placeholder="Enter your email"
                        value={registerForm.email}
                        onChange={(e) =>
                          setRegisterForm({
                            ...registerForm,
                            email: e.target.value,
                          })
                        }
                        required
                        disabled={isLoading}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="register-password">Password</Label>
                      <Input
                        id="register-password"
                        data-testid="register-password-input"
                        type="password"
                        placeholder="Create a password"
                        value={registerForm.password}
                        onChange={(e) =>
                          setRegisterForm({
                            ...registerForm,
                            password: e.target.value,
                          })
                        }
                        required
                        disabled={isLoading}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="register-confirm">Confirm Password</Label>
                      <Input
                        id="register-confirm"
                        data-testid="register-confirm-input"
                        type="password"
                        placeholder="Confirm your password"
                        value={registerForm.confirmPassword}
                        onChange={(e) =>
                          setRegisterForm({
                            ...registerForm,
                            confirmPassword: e.target.value,
                          })
                        }
                        required
                        disabled={isLoading}
                      />
                    </div>
                  </CardContent>
                  <CardFooter>
                    <Button
                      data-testid="register-submit-btn"
                      type="submit"
                      className="w-full text-white border-0 hover:opacity-90 transition-opacity shadow-[0_0_30px_rgba(20,184,166,0.35)]"
                      style={{ backgroundColor: "var(--console-accent)" }}
                      disabled={isLoading}
                    >
                      {isLoading
                        ? "Creating account..."
                        : "Create Admin Account"}
                    </Button>
                  </CardFooter>
                </form>
              </Card>
            </TabsContent>
          </Tabs>
        )}

        {/* Secure-access footer */}
        <div
          className="flex items-center justify-center gap-1.5 mt-6 font-telemetry text-[10px] uppercase tracking-[0.18em]"
          style={{ color: "var(--console-muted)" }}
        >
          <ShieldCheck
            className="h-3.5 w-3.5"
            style={{ color: "var(--console-accent)" }}
          />
          {branding.system_name} · Secure Access
        </div>
      </div>
    </div>
  );
};

export default Login;
