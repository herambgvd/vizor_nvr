import React from "react";
import { useNavigate } from "react-router-dom";
import { Video, ChevronDown, Settings as SettingsIcon, LogOut } from "lucide-react";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from "../ui/dropdown-menu";
import { Avatar, AvatarFallback } from "../ui/avatar";
import { ChangePasswordDialogTrigger } from "../auth/ChangePasswordDialog";
import { useAuth } from "../../context/AuthContext";
import useBranding from "../../hooks/useBranding";
import TopNav from "./TopNav";

const initials = (name) =>
  !name ? "U" : name.split(" ").map((n) => n[0]).join("").toUpperCase().slice(0, 2);

export default function TopHeader({ title }) {
  const navigate = useNavigate();
  const { user, isAdmin, logout } = useAuth();
  const branding = useBranding();

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  return (
    <header
      className="flex items-center gap-3 px-3 console-panel border-b"
      style={{ height: "var(--console-header-h)", borderColor: "var(--console-border)" }}
    >
      <div className="flex items-center gap-2">
        {branding.logo_url ? (
          <img
            src={branding.logo_url}
            alt={branding.system_name}
            className="h-7 w-7 rounded object-contain"
          />
        ) : (
          <div className="h-6 w-6 rounded bg-[var(--console-accent)] flex items-center justify-center">
            <Video className="h-3.5 w-3.5 text-white" />
          </div>
        )}
        <span className="text-sm font-semibold tracking-tight">{branding.system_name}</span>
      </div>
      <div className="h-4 w-px" style={{ background: "var(--console-border)" }} />

      {/* Primary navigation — horizontal, frees the left gutter for content. */}
      <TopNav />

      <div className="ml-auto flex items-center gap-2">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button className="flex items-center gap-2 px-2 py-1 rounded hover:bg-[var(--console-hover)]">
              <Avatar className="h-7 w-7">
                <AvatarFallback className="bg-gradient-to-br from-blue-500 to-cyan-500 text-white text-[11px]">
                  {initials(user?.username)}
                </AvatarFallback>
              </Avatar>
              <span className="text-xs hidden md:block" style={{ color: "var(--console-text)" }}>{user?.username}</span>
              <ChevronDown className="h-3.5 w-3.5" style={{ color: "var(--console-muted)" }} />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-52 console-panel border-border">
            <DropdownMenuLabel className="text-[11px] uppercase tracking-wider" style={{ color: "var(--console-muted)" }}>
              {isAdmin ? "Administrator" : user?.role_name || "User"}
            </DropdownMenuLabel>
            <DropdownMenuSeparator style={{ background: "var(--console-border)" }} />
            <DropdownMenuItem onClick={() => navigate("/settings")} className="focus:bg-[var(--console-hover)] focus:text-[var(--console-text)]">
              <SettingsIcon className="h-4 w-4 mr-2" /> Settings
            </DropdownMenuItem>
            <ChangePasswordDialogTrigger />
            <DropdownMenuSeparator style={{ background: "var(--console-border)" }} />
            <DropdownMenuItem
              onClick={handleLogout}
              className="text-rose-400 focus:bg-rose-500/10 focus:text-rose-300"
            >
              <LogOut className="h-4 w-4 mr-2" /> Logout
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
