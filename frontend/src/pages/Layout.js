// =============================================================================
// Layout — Horizontal top-bar shell
// =============================================================================
// 4 primary nav items: Dashboard, Cameras, Events, Settings.
// Settings hosts a sub-menu (Notifications / Monitoring / Audit Log /
// Configuration). Playback nested under Cameras.
// =============================================================================

import React, { useState, useEffect, useRef } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  Video,
  LayoutDashboard,
  Camera,
  Play,
  Activity,
  Settings,
  Bell,
  BellRing,
  Bookmark,
  UserSquare2,
  ChevronDown,
  LogOut,
  User,
  Menu,
  X,
  Key,
} from "lucide-react";
import { cn } from "../lib/utils";
import { useAuth } from "../context/AuthContext";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "../components/ui/dropdown-menu";
import { Avatar, AvatarFallback } from "../components/ui/avatar";
import { ChangePasswordDialogTrigger } from "../components/auth/ChangePasswordDialog";
import {
  LiveEventProvider,
  LiveEventDrawer,
} from "../components/nvr/LiveEventDrawer";

const Layout = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, isAdmin, logout } = useAuth();
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => setMobileOpen(false), [location.pathname]);

  // Primary nav — 4 items. Each may have `children` for hover/click sub-menu.
  const primaryNav = [
    {
      path: "/",
      label: "Live",
      icon: LayoutDashboard,
      exact: true,
    },
    {
      path: "/cameras",
      label: "Cameras",
      icon: Camera,
    },
    {
      path: "/playback",
      label: "Playback",
      icon: Play,
    },
    {
      path: "/events",
      label: "Events",
      icon: Bell,
    },
    {
      path: "/bookmarks",
      label: "Bookmarks",
      icon: Bookmark,
    },
    {
      path: "/settings",
      label: "Settings",
      icon: Settings,
    },
  ];

  const isActive = (item) => {
    if (item.exact) return location.pathname === item.path;
    if (item.children) {
      return item.children.some((c) => location.pathname.startsWith(c.path));
    }
    return location.pathname.startsWith(item.path);
  };

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  const getInitials = (name) =>
    !name
      ? "U"
      : name
          .split(" ")
          .map((n) => n[0])
          .join("")
          .toUpperCase()
          .slice(0, 2);

  // ── Top-bar item with optional dropdown ─────────────────────────────────
  const TopNavItem = ({ item }) => {
    const active = isActive(item);
    const Icon = item.icon;
    const [hoverOpen, setHoverOpen] = useState(false);
    const closeTimer = useRef(null);

    const cancelClose = () => {
      if (closeTimer.current) {
        clearTimeout(closeTimer.current);
        closeTimer.current = null;
      }
    };
    const scheduleClose = () => {
      cancelClose();
      closeTimer.current = setTimeout(() => setHoverOpen(false), 120);
    };

    if (!item.children) {
      return (
        <Link
          to={item.path}
          className={cn(
            "relative inline-flex items-center gap-2 px-3 h-10 rounded-lg text-sm font-medium transition-colors",
            active
              ? "text-white bg-[var(--console-raised)]"
              : "text-[var(--console-muted)] hover:text-white hover:bg-[var(--console-raised)]",
          )}
        >
          <Icon className="h-[16px] w-[16px]" />
          {item.label}
          {active && (
            <span className="absolute left-1/2 -translate-x-1/2 -bottom-[10px] h-[2px] w-8 rounded-full bg-gradient-to-r from-teal-400 to-blue-400 shadow-[0_0_8px_rgba(20,184,166,0.6)]" />
          )}
        </Link>
      );
    }

    return (
      <div
        className="relative"
        onMouseEnter={() => {
          cancelClose();
          setHoverOpen(true);
        }}
        onMouseLeave={scheduleClose}
      >
        <Link
          to={item.path}
          className={cn(
            "relative inline-flex items-center gap-2 px-3 h-10 rounded-lg text-sm font-medium transition-colors",
            active
              ? "text-white bg-[var(--console-raised)]"
              : "text-[var(--console-muted)] hover:text-white hover:bg-[var(--console-raised)]",
          )}
        >
          <Icon className="h-[16px] w-[16px]" />
          {item.label}
          <ChevronDown className="h-3.5 w-3.5 opacity-70" />
          {active && (
            <span className="absolute left-1/2 -translate-x-1/2 -bottom-[10px] h-[2px] w-8 rounded-full bg-gradient-to-r from-teal-400 to-blue-400 shadow-[0_0_8px_rgba(20,184,166,0.6)]" />
          )}
        </Link>
        {hoverOpen && (
          <div
            className="absolute left-0 top-full mt-1 min-w-[200px] rounded-lg border border-[var(--console-border)] backdrop-blur-xl shadow-xl p-1 z-50"
            style={{ backgroundColor: 'var(--console-panel)' }}
            onMouseEnter={cancelClose}
            onMouseLeave={scheduleClose}
          >
            {item.children.map((c) => {
              const ChildIcon = c.icon;
              const childActive = location.pathname === c.path
                || (c.path !== "/" && location.pathname.startsWith(c.path));
              return (
                <Link
                  key={c.path}
                  to={c.path}
                  onClick={() => setHoverOpen(false)}
                  className={cn(
                    "flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors",
                    childActive
                      ? "bg-[var(--console-raised)] text-white"
                      : "text-[var(--console-muted)] hover:text-white hover:bg-white/5",
                  )}
                >
                  <ChildIcon className="h-4 w-4" />
                  {c.label}
                </Link>
              );
            })}
          </div>
        )}
      </div>
    );
  };

  // ── Mobile drawer item (flat — children listed inline) ───────────────────
  const MobileNavItem = ({ item }) => {
    const Icon = item.icon;
    return (
      <>
        <Link
          to={item.path}
          onClick={() => setMobileOpen(false)}
          className={cn(
            "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all",
            isActive(item)
              ? "bg-[var(--console-raised)] text-white"
              : "text-[var(--console-muted)] hover:text-white hover:bg-[var(--console-raised)]",
          )}
        >
          <Icon className="h-[18px] w-[18px]" />
          <span className="font-medium">{item.label}</span>
        </Link>
        {item.children && (
          <div className="ml-6 mt-1 space-y-0.5 mb-1">
            {item.children.map((c) => {
              const ChildIcon = c.icon;
              return (
                <Link
                  key={c.path}
                  to={c.path}
                  onClick={() => setMobileOpen(false)}
                  className={cn(
                    "flex items-center gap-2 px-3 py-1.5 rounded-md text-[13px] transition-colors",
                    location.pathname.startsWith(c.path)
                      ? "text-white bg-[var(--console-raised)]"
                      : "text-muted-foreground hover:text-white",
                  )}
                >
                  <ChildIcon className="h-3.5 w-3.5" />
                  {c.label}
                </Link>
              );
            })}
          </div>
        )}
      </>
    );
  };

  return (
    <LiveEventProvider>
    <div className="relative min-h-screen h-screen bg-[var(--console-bg)] text-foreground flex flex-col overflow-hidden">
      <div className="aurora" />

      {/* Top bar */}
      <header className="relative z-20 flex items-center h-14 px-4 md:px-6 border-b border-[var(--console-border)] backdrop-blur-xl" style={{ backgroundColor: 'var(--console-panel)' }}>
        {/* Brand */}
        <Link to="/" className="flex items-center gap-2.5 mr-6 flex-shrink-0">
          <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-teal-500 to-blue-500 flex items-center justify-center shadow-[0_0_20px_rgba(20,184,166,0.4)]">
            <Video className="h-4 w-4 text-white" />
          </div>
          <div className="hidden sm:block leading-tight">
            <p className="text-[14px] font-semibold tracking-tight">GVD Pro</p>
            <p className="text-[10px] text-muted-foreground -mt-0.5">Network Video Recorder</p>
          </div>
        </Link>

        {/* Primary nav — desktop */}
        <nav className="hidden md:flex items-center gap-1 flex-1">
          {primaryNav.map((item) => (
            <TopNavItem key={item.path} item={item} />
          ))}
        </nav>

        {/* Right — user */}
        <div className="ml-auto flex items-center gap-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-[var(--console-raised)] transition-colors">
                <Avatar className="h-8 w-8 ring-2 ring-white/10">
                  <AvatarFallback className="text-white text-xs font-medium" style={{ backgroundColor: 'var(--console-accent)' }}>
                    {getInitials(user?.username)}
                  </AvatarFallback>
                </Avatar>
                <div className="hidden md:block text-left leading-tight">
                  <p className="text-[13px] font-medium truncate max-w-[120px]">{user?.username}</p>
                  <p className="text-[10px] text-muted-foreground truncate max-w-[120px]">
                    {isAdmin ? "Administrator" : user?.role_name || "User"}
                  </p>
                </div>
                <ChevronDown className="h-3.5 w-3.5 text-muted-foreground hidden md:block" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56 backdrop-blur-xl border-[var(--console-border)]" style={{ backgroundColor: 'var(--console-panel)' }}>
              <DropdownMenuLabel className="text-[var(--console-muted)] text-[11px] uppercase tracking-wider">
                My Account
              </DropdownMenuLabel>
              <DropdownMenuSeparator className="bg-white/10" />
              <DropdownMenuItem onClick={() => navigate("/settings")} className="focus:bg-[var(--console-raised)] focus:text-white">
                <User className="h-4 w-4 mr-2" />
                Profile
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => navigate("/settings")} className="focus:bg-[var(--console-raised)] focus:text-white">
                <Settings className="h-4 w-4 mr-2" />
                Settings
              </DropdownMenuItem>
              <ChangePasswordDialogTrigger />
              <DropdownMenuSeparator className="bg-white/10" />
              <DropdownMenuItem
                onClick={handleLogout}
                className="text-rose-400 focus:bg-rose-500/10 focus:text-rose-300"
              >
                <LogOut className="h-4 w-4 mr-2" />
                Logout
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          {/* Mobile menu trigger */}
          <button
            onClick={() => setMobileOpen(!mobileOpen)}
            className="md:hidden p-2 rounded-md text-[var(--console-text)] hover:bg-[var(--console-raised)] transition-colors"
          >
            {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </header>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div
          className="md:hidden fixed inset-0 z-30 bg-black/60 backdrop-blur-sm"
          onClick={() => setMobileOpen(false)}
        />
      )}
      <aside
        className={cn(
          "md:hidden fixed left-0 top-14 bottom-0 z-40 w-72 flex flex-col",
          "backdrop-blur-xl border-r border-[var(--console-border)] bg-[var(--console-panel)]",
          "transition-transform duration-300 ease-in-out",
          mobileOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <nav className="flex-1 p-2 space-y-0.5 overflow-y-auto">
          {primaryNav.map((item) => (
            <MobileNavItem key={item.path} item={item} />
          ))}
        </nav>
        <div className="p-2 border-t border-border">
          <button
            onClick={handleLogout}
            className="w-full flex items-center gap-2 px-3 py-2 rounded-md text-rose-400 hover:bg-rose-500/10"
          >
            <LogOut className="h-4 w-4" /> Logout
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="relative z-10 flex-1 min-h-0 overflow-auto">
        <Outlet />
      </main>

      <LiveEventDrawer />
    </div>
    </LiveEventProvider>
  );
};

export default Layout;
