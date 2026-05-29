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

const initials = (name) =>
  !name ? "U" : name.split(" ").map((n) => n[0]).join("").toUpperCase().slice(0, 2);

export default function TopHeader({ title }) {
  const navigate = useNavigate();
  const { user, isAdmin, logout } = useAuth();

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
        <div className="h-6 w-6 rounded bg-gradient-to-br from-teal-500 to-blue-500 flex items-center justify-center">
          <Video className="h-3.5 w-3.5 text-white" />
        </div>
        <span className="text-sm font-semibold tracking-tight">GVD Pro</span>
      </div>
      <div className="h-4 w-px" style={{ background: "var(--console-border)" }} />
      <span className="text-sm text-zinc-400">{title}</span>

      <div className="ml-auto flex items-center gap-2">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button className="flex items-center gap-2 px-2 py-1 rounded hover:bg-white/5">
              <Avatar className="h-7 w-7">
                <AvatarFallback className="bg-gradient-to-br from-blue-500 to-cyan-500 text-white text-[11px]">
                  {initials(user?.username)}
                </AvatarFallback>
              </Avatar>
              <span className="text-xs text-zinc-300 hidden md:block">{user?.username}</span>
              <ChevronDown className="h-3.5 w-3.5 text-zinc-500" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-52 console-panel border-border">
            <DropdownMenuLabel className="text-zinc-400 text-[11px] uppercase tracking-wider">
              {isAdmin ? "Administrator" : user?.role_name || "User"}
            </DropdownMenuLabel>
            <DropdownMenuSeparator className="bg-white/10" />
            <DropdownMenuItem onClick={() => navigate("/settings")} className="focus:bg-white/5 focus:text-white">
              <SettingsIcon className="h-4 w-4 mr-2" /> Settings
            </DropdownMenuItem>
            <ChangePasswordDialogTrigger />
            <DropdownMenuSeparator className="bg-white/10" />
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
