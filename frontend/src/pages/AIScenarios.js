// =============================================================================
// AI Scenarios — Marketplace-style catalog of analytics capabilities.
//
// Browse the full Metropolis-backed scenario list. Filter by category,
// tier, or build status. GA scenarios can be enabled on cameras from
// the Camera detail page; planned scenarios show a "Coming Soon" badge.
// =============================================================================

import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Sparkles,
  ShieldCheck,
  Users,
  Car,
  Search,
  Activity,
  AlertTriangle,
  Filter,
} from "lucide-react";

import { listScenarios } from "../api/ai";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Input } from "../components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";

// Category → icon mapping
const CATEGORY_ICONS = {
  person: Users,
  vehicle: Car,
  behavior: Activity,
  safety: ShieldCheck,
  security: AlertTriangle,
  search: Search,
};

const TIER_COLORS = {
  free: "bg-slate-100 text-slate-700",
  pro: "bg-blue-100 text-blue-700",
  business: "bg-purple-100 text-purple-700",
  enterprise: "bg-amber-100 text-amber-700",
};

const STATUS_COLORS = {
  ga: "bg-emerald-100 text-emerald-700",
  beta: "bg-yellow-100 text-yellow-700",
  planned: "bg-slate-100 text-slate-500",
};

export default function AIScenarios() {
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("all");
  const [tier, setTier] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");

  const {
    data: scenarios = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ["ai-scenarios"],
    queryFn: () => listScenarios(),
  });

  // Client-side filtering: catalog stays small (~30 rows) so no need to
  // round-trip on every keystroke.
  const filtered = useMemo(() => {
    return scenarios.filter((s) => {
      if (category !== "all" && s.category !== category) return false;
      if (tier !== "all" && s.tier !== tier) return false;
      if (statusFilter !== "all" && s.status !== statusFilter) return false;
      if (search) {
        const q = search.toLowerCase();
        const haystack = `${s.name} ${s.description} ${(s.use_cases || []).join(
          " "
        )}`.toLowerCase();
        if (!haystack.includes(q)) return false;
      }
      return true;
    });
  }, [scenarios, category, tier, statusFilter, search]);

  if (isLoading) {
    return (
      <div className="p-6">
        <p className="text-slate-500">Loading scenarios…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <p className="text-red-600">Failed to load scenarios: {error.message}</p>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-start gap-3">
        <div className="p-2 rounded-lg bg-gradient-to-br from-blue-500 to-purple-600 text-white">
          <Sparkles size={24} />
        </div>
        <div>
          <h1 className="text-2xl font-bold">AI Scenarios</h1>
          <p className="text-sm text-slate-500">
            {scenarios.length} analytics capabilities ready to deploy.
            Enable on individual cameras from the Camera detail page.
          </p>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3 p-4 rounded-lg border bg-white">
        <Filter size={16} className="text-slate-400" />
        <Input
          placeholder="Search scenarios, use cases…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-64"
        />
        <Select value={category} onValueChange={setCategory}>
          <SelectTrigger className="w-44">
            <SelectValue placeholder="Category" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All categories</SelectItem>
            <SelectItem value="person">Person</SelectItem>
            <SelectItem value="vehicle">Vehicle</SelectItem>
            <SelectItem value="behavior">Behavior</SelectItem>
            <SelectItem value="safety">Safety</SelectItem>
            <SelectItem value="security">Security</SelectItem>
            <SelectItem value="search">Search</SelectItem>
          </SelectContent>
        </Select>
        <Select value={tier} onValueChange={setTier}>
          <SelectTrigger className="w-44">
            <SelectValue placeholder="Tier" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All tiers</SelectItem>
            <SelectItem value="free">Free</SelectItem>
            <SelectItem value="pro">Pro</SelectItem>
            <SelectItem value="business">Business</SelectItem>
            <SelectItem value="enterprise">Enterprise</SelectItem>
          </SelectContent>
        </Select>
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-44">
            <SelectValue placeholder="Status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            <SelectItem value="ga">GA — ship-ready</SelectItem>
            <SelectItem value="beta">Beta</SelectItem>
            <SelectItem value="planned">Coming soon</SelectItem>
          </SelectContent>
        </Select>
        <p className="text-sm text-slate-500 ml-auto">
          {filtered.length} of {scenarios.length}
        </p>
      </div>

      {/* Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {filtered.map((s) => {
          const Icon = CATEGORY_ICONS[s.category] || Sparkles;
          const dim = s.status !== "ga";
          return (
            <Card
              key={s.slug}
              className={dim ? "opacity-70 hover:opacity-100 transition" : ""}
            >
              <CardHeader>
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <div className="p-2 rounded-md bg-slate-100 text-slate-700">
                      <Icon size={18} />
                    </div>
                    <CardTitle className="text-base">{s.name}</CardTitle>
                  </div>
                  <div className="flex flex-col items-end gap-1">
                    <Badge className={TIER_COLORS[s.tier]}>{s.tier}</Badge>
                    <Badge className={STATUS_COLORS[s.status]} variant="outline">
                      {s.status === "ga"
                        ? "Available"
                        : s.status === "beta"
                        ? "Beta"
                        : "Coming soon"}
                    </Badge>
                  </div>
                </div>
                <CardDescription className="text-xs pt-2">
                  {s.description}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3 text-xs">
                {s.use_cases?.length ? (
                  <div>
                    <p className="text-slate-500 mb-1">Use cases</p>
                    <div className="flex flex-wrap gap-1">
                      {s.use_cases.slice(0, 5).map((u) => (
                        <span
                          key={u}
                          className="px-2 py-0.5 rounded bg-slate-50 text-slate-700"
                        >
                          {u.replace(/_/g, " ")}
                        </span>
                      ))}
                    </div>
                  </div>
                ) : null}
                {s.requires_models?.length ? (
                  <div>
                    <p className="text-slate-500 mb-1">Powered by</p>
                    <div className="flex flex-wrap gap-1">
                      {s.requires_models.map((m) => (
                        <span
                          key={m}
                          className="px-2 py-0.5 rounded bg-slate-50 text-slate-500 font-mono text-[10px]"
                        >
                          {m}
                        </span>
                      ))}
                    </div>
                  </div>
                ) : null}
                {s.metropolis_service ? (
                  <p className="text-slate-400 text-[10px]">
                    Runs on{" "}
                    <span className="font-mono">{s.metropolis_service}</span>
                  </p>
                ) : null}
              </CardContent>
            </Card>
          );
        })}
      </div>

      {filtered.length === 0 ? (
        <div className="text-center py-12 text-slate-500">
          No scenarios match the current filters.
        </div>
      ) : null}
    </div>
  );
}
