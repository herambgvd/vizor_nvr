// =============================================================================
// Layout — Vercel-style dark shell with aurora glow + glass sidebar
// =============================================================================

import React, { useState, useEffect } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  Video,
  LayoutDashboard,
  Camera,
  Play,
  LayoutGrid,
  Activity,
  Settings,
  Shield,
  Bell,
  BellRing,
  ChevronLeft,
  ChevronRight,
  LogOut,
  User,
  Menu,
  X,
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

const Layout = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, isAdmin, logout } = useAuth();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => setMobileOpen(false), [location.pathname]);
  useEffect(() => {
    const onResize = () => window.innerWidth >= 768 && setMobileOpen(false);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const navItems = [
    { path: "/", label: "Dashboard", icon: LayoutDashboard, desc: "Overview" },
    { path: "/cameras", label: "Cameras", icon: Camera, desc: "Manage cameras" },
    { path: "/playback", label: "Playback", icon: Play, desc: "Recordings" },
    { path: "/playback/multi", label: "Multi-Playback", icon: LayoutGrid, desc: "Sync grid" },
    { path: "/events", label: "Events", icon: Bell, desc: "Alarms & events" },
    { path: "/notifications", label: "Notifications", icon: BellRing, desc: "Webhooks" },
    { path: "/monitoring", label: "Monitoring", icon: Activity, desc: "System health" },
    { path: "/settings", label: "Settings", icon: Settings, desc: "Configuration" },
    ...(isAdmin
      ? [{ path: "/audit", label: "Audit Log", icon: Shield, desc: "Activity" }]
      : []),
  ];

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

  const isItemActive = (path) =>
    path === "/" ? location.pathname === "/" : location.pathname.startsWith(path);

  const NavItem = ({ item, onClick }) => {
    const active = isItemActive(item.path);
    const Icon = item.icon;
    return (
      <Link
        to={item.path}
        onClick={onClick}
        className={cn(
          "group relative flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all",
          active
            ? "bg-white/[0.06] text-white"
            : "text-zinc-400 hover:text-white hover:bg-white/[0.04]",
          collapsed && "justify-center px-2",
        )}
      >
        {active && (
          <span className="absolute left-0 top-1/2 -translate-y-1/2 h-5 w-[3px] rounded-r-full bg-gradient-to-b from-blue-400 to-cyan-400 shadow-[0_0_8px_rgba(59,130,246,0.6)]" />
        )}
        <Icon className={cn("h-[18px] w-[18px] flex-shrink-0", active ? "text-white" : "text-zinc-500 group-hover:text-zinc-300")} />
        {!collapsed && (
          <div className="flex-1 min-w-0">
            <p className="font-medium truncate">{item.label}</p>
            {!active && (
              <p className="text-[11px] text-zinc-600 truncate">{item.desc}</p>
            )}
          </div>
        )}
      </Link>
    );
  };

  return (
    <div className="relative min-h-screen h-screen bg-background text-foreground flex overflow-hidden">
      {/* Top-right aurora glow — sits behind everything */}
      <div className="aurora" />

      {/* Mobile header */}
      <header className="md:hidden fixed top-0 left-0 right-0 z-40 h-14 glass flex items-center justify-between px-4">
        <div className="flex items-center gap-2.5">
          <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-blue-500 to-cyan-400 flex items-center justify-center shadow-[0_0_20px_rgba(59,130,246,0.4)]">
            <Video className="h-4 w-4 text-white" />
          </div>
          <span className="font-semibold tracking-tight">GVD Pro</span>
        </div>
        <button
          onClick={() => setMobileOpen(!mobileOpen)}
          className="p-2 rounded-md text-zinc-300 hover:bg-white/[0.06] transition-colors"
        >
          {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </header>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div
          className="md:hidden fixed inset-0 z-30 bg-black/60 backdrop-blur-sm"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Desktop sidebar */}
      <aside
        className={cn(
          "relative z-10 hidden md:flex flex-col",
          "border-r border-white/[0.07] bg-zinc-950/40 backdrop-blur-xl",
          "transition-[width] duration-300 ease-in-out",
          collapsed ? "w-[68px]" : "w-64",
        )}
      >
        {/* Logo */}
        <div className={cn("flex items-center gap-3 px-4 h-16 border-b border-white/[0.07]", collapsed && "justify-center px-2")}>
          <div className="h-9 w-9 rounded-xl bg-gradient-to-br from-blue-500 to-cyan-400 flex items-center justify-center shadow-[0_0_24px_rgba(59,130,246,0.45)] flex-shrink-0">
            <Video className="h-[18px] w-[18px] text-white" />
          </div>
          {!collapsed && (
            <div className="min-w-0">
              <p className="text-[15px] font-semibold tracking-tight">GVD Pro</p>
              <p className="text-[11px] text-zinc-500">Network Video Recorder</p>
            </div>
          )}
        </div>

        {/* Nav */}
        <nav className="flex-1 p-2 space-y-0.5 overflow-y-auto">
          {navItems.map((item) => (
            <NavItem key={item.path} item={item} />
          ))}
        </nav>

        {/* Collapse */}
        <div className="p-2 border-t border-white/[0.07]">
          <button
            onClick={() => setCollapsed(!collapsed)}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-md text-zinc-500 hover:text-white hover:bg-white/[0.06] transition-colors"
          >
            {collapsed ? <ChevronRight className="h-4 w-4" /> : (
              <>
                <ChevronLeft className="h-4 w-4" />
                <span className="text-[13px]">Collapse</span>
              </>
            )}
          </button>
        </div>

        {/* User */}
        <div className={cn("p-2 border-t border-white/[0.07]", collapsed && "flex justify-center")}>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                className={cn(
                  "flex items-center gap-3 w-full px-2 py-2 rounded-lg hover:bg-white/[0.06] transition-colors",
                  collapsed && "w-auto",
                )}
              >
                <Avatar className="h-8 w-8 ring-2 ring-white/10">
                  <AvatarFallback className="bg-gradient-to-br from-blue-500 to-cyan-500 text-white text-xs font-medium">
                    {getInitials(user?.username)}
                  </AvatarFallback>
                </Avatar>
                {!collapsed && (
                  <div className="flex-1 min-w-0 text-left">
                    <p className="text-sm font-medium truncate">{user?.username}</p>
                    <p className="text-[11px] text-zinc-500 truncate">
                      {isAdmin ? "Administrator" : user?.role_name || "User"}
                    </p>
                  </div>
                )}
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56 bg-zinc-950/95 backdrop-blur-xl border-white/10">
              <DropdownMenuLabel className="text-zinc-400 text-[11px] uppercase tracking-wider">
                My Account
              </DropdownMenuLabel>
              <DropdownMenuSeparator className="bg-white/10" />
              <DropdownMenuItem onClick={() => navigate("/settings")} className="focus:bg-white/[0.06] focus:text-white">
                <User className="h-4 w-4 mr-2" />
                Profile
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => navigate("/settings")} className="focus:bg-white/[0.06] focus:text-white">
                <Settings className="h-4 w-4 mr-2" />
                Settings
              </DropdownMenuItem>
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
        </div>
      </aside>

      {/* Mobile sidebar */}
      <aside
        className={cn(
          "md:hidden fixed left-0 top-14 bottom-0 z-40 w-72 flex flex-col",
          "glass border-r border-white/[0.07]",
          "transition-transform duration-300 ease-in-out",
          mobileOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <nav className="flex-1 p-2 space-y-0.5 overflow-y-auto">
          {navItems.map((item) => (
            <NavItem key={item.path} item={item} onClick={() => setMobileOpen(false)} />
          ))}
        </nav>
        <div className="p-2 border-t border-white/[0.07]">
          <button
            onClick={handleLogout}
            className="w-full flex items-center gap-2 px-3 py-2 rounded-md text-rose-400 hover:bg-rose-500/10"
          >
            <LogOut className="h-4 w-4" /> Logout
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="relative z-10 flex-1 h-full overflow-auto pt-14 md:pt-0">
        <Outlet />
      </main>
    </div>
  );
};

export default Layout;
