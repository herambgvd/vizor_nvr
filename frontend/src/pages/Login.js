// =============================================================================
// Login Page - User Authentication
// =============================================================================
// Login and registration page with clean white theme.
// =============================================================================

import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Video, Eye, EyeOff, LogIn, UserPlus } from "lucide-react";
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

const Login = () => {
  const navigate = useNavigate();
  const { login, register } = useAuth();

  // Form states
  const [isLoading, setIsLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

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
   * Handle login form submission
   */
  const handleLogin = async (e) => {
    e.preventDefault();
    setIsLoading(true);

    try {
      await login(loginForm.username, loginForm.password);
      toast.success("Welcome back!");
      navigate("/");
    } catch (error) {
      const message =
        error.response?.data?.detail ||
        "Login failed. Please check your credentials.";
      toast.error(message);
    } finally {
      setIsLoading(false);
    }
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
      const message =
        error.response?.data?.detail ||
        "Registration failed. Please try again.";
      toast.error(message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="relative min-h-screen bg-background text-foreground flex overflow-hidden">
      {/* Aurora glow — top-right blue/cyan bloom */}
      <div className="aurora" />

      {/* Subtle dot grid */}
      <div
        className="pointer-events-none absolute inset-0 z-0 opacity-[0.05]"
        style={{
          backgroundImage:
            "radial-gradient(circle at 1px 1px, rgba(255,255,255,0.7) 1px, transparent 0)",
          backgroundSize: "32px 32px",
        }}
      />

      {/* Left Side - Branding */}
      <div className="hidden lg:flex lg:w-1/2 relative z-10">
        <div className="relative z-10 flex flex-col justify-center w-full p-16 text-white">
          <div className="flex items-center gap-3 mb-12">
            <div className="h-12 w-12 rounded-xl bg-gradient-to-br from-blue-500 to-cyan-400 flex items-center justify-center shadow-[0_0_40px_rgba(59,130,246,0.45)]">
              <Video className="h-6 w-6 text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">GVD Pro</h1>
              <p className="text-muted-foreground text-sm">Network Video Recorder</p>
            </div>
          </div>

          <div className="max-w-md">
            <h2 className="text-5xl font-semibold tracking-tight leading-[1.05] mb-6 text-balance">
              <span className="text-gradient-blue">Surveillance,</span>
              <br />
              rebuilt for operators.
            </h2>
            <p className="text-zinc-400 leading-relaxed text-[15px]">
              ONVIF-native recording with privacy masking, signed evidence
              export, two-factor auth, and per-camera RBAC — all in a single
              dark dashboard.
            </p>
          </div>

          <div className="mt-12 grid grid-cols-2 gap-x-6 gap-y-3 max-w-md">
            {[
              "Multi-stream H.264/265",
              "Motion-triggered events",
              "S.M.A.R.T disk health",
              "Signed evidence bundles",
              "TOTP 2FA",
              "Per-camera ACL",
            ].map((feature) => (
              <div
                key={feature}
                className="flex items-center gap-2 text-zinc-400 text-[13px]"
              >
                <div className="h-1.5 w-1.5 rounded-full bg-gradient-to-br from-blue-400 to-cyan-400 shadow-[0_0_6px_rgba(59,130,246,0.7)]" />
                {feature}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Right Side - Auth Forms */}
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="w-full max-w-md">
          {/* Mobile Logo */}
          <div className="lg:hidden flex items-center justify-center gap-3 mb-8">
            <div className="p-2 bg-primary rounded-lg">
              <Video className="h-6 w-6 text-white" />
            </div>
            <span
              className="text-xl font-bold text-white"
              style={{ fontFamily: "Manrope, sans-serif" }}
            >
              GVD Pro
            </span>
          </div>

          {/* Loading state */}
          {setupRequired === null && (
            <div className="flex items-center justify-center py-16">
              <div className="text-muted-foreground text-sm">
                Checking system status…
              </div>
            </div>
          )}

          {/* Normal login — no register tab */}
          {setupRequired === false && (
            <Card className="border-border bg-card/60 backdrop-blur-xl shadow-[0_0_60px_rgba(59,130,246,0.10)]">
              <CardHeader className="space-y-1">
                <CardTitle
                  className="text-2xl"
                  style={{ fontFamily: "Manrope, sans-serif" }}
                >
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
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-zinc-400"
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
                    className="w-full bg-gradient-to-r from-blue-500 to-cyan-400 hover:from-blue-400 hover:to-cyan-300 text-white border-0 shadow-[0_0_30px_rgba(59,130,246,0.35)]"
                    disabled={isLoading}
                  >
                    {isLoading ? "Signing in..." : "Sign In"}
                  </Button>
                </CardFooter>
              </form>
            </Card>
          )}

          {/* First-time setup — show both tabs, default to register */}
          {setupRequired === true && (
            <Tabs defaultValue="register" className="w-full">
              <TabsList className="grid w-full grid-cols-2 mb-6">
                <TabsTrigger
                  data-testid="login-tab"
                  value="login"
                  className=""
                >
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
                <Card className="border-border bg-card/60 backdrop-blur-xl shadow-[0_0_60px_rgba(59,130,246,0.10)]">
                  <CardHeader className="space-y-1">
                    <CardTitle
                      className="text-2xl"
                      style={{ fontFamily: "Manrope, sans-serif" }}
                    >
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
                            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-zinc-400"
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
                        className="w-full bg-gradient-to-r from-blue-500 to-cyan-400 hover:from-blue-400 hover:to-cyan-300 text-white border-0 shadow-[0_0_30px_rgba(59,130,246,0.35)]"
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
                <Card className="border-border bg-card/60 backdrop-blur-xl shadow-[0_0_60px_rgba(59,130,246,0.10)]">
                  <CardHeader className="space-y-1">
                    <CardTitle
                      className="text-2xl"
                      style={{ fontFamily: "Manrope, sans-serif" }}
                    >
                      Create administrator account
                    </CardTitle>
                    <CardDescription>
                      Set up the primary admin account for GVD Pro
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
                        <Label htmlFor="register-confirm">
                          Confirm Password
                        </Label>
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
                        className="w-full bg-gradient-to-r from-blue-500 to-cyan-400 hover:from-blue-400 hover:to-cyan-300 text-white border-0 shadow-[0_0_30px_rgba(59,130,246,0.35)]"
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
        </div>
      </div>
    </div>
  );
};

export default Login;
