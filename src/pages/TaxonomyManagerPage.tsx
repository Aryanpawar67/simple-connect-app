import { useState, useEffect, useCallback } from "react";
import { Download, RefreshCw, GitMerge, Database, Layers, FolderTree, BookOpen, ChevronDown, ChevronUp, History, FileCheck, ArrowRight, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import { Slider } from "@/components/ui/slider";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";
import { apiUrl } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ActiveTab = "stats" | "merge" | "history";

interface OverviewData {
  taxonomy_size: number;
  scraped_count: number;
  new_skills_count: number;
  master_filename: string;
  is_original: boolean;
}

interface TaxonomyStats {
  total_skills: number;
  sheet1_count: number;
  sheet2_count: number;
  domain_count: number;
  subdomain_count: number;
  skill_cluster_count: number;
  domain_breakdown: Record<string, number>;
  classification_breakdown: Record<string, number>;
  master_filename: string;
  is_original: boolean;
}

interface NewSkill {
  db_id: number;
  skill_name: string;
  proposed_domain: string;
  proposed_subdomain: string;
  proposed_cluster: string;
  proposed_classification: string;
  proposed_criticality: string;
  source: string;
  confidence_score: number;
  category: string;
  subcategory: string;
  skill_type: string;
}

interface CompareResult {
  total_db_skills: number;
  matched: number;
  new_skills: NewSkill[];
  unmappable: NewSkill[];
  master_filename: string;
}

interface EditedSkill extends NewSkill {
  selected: boolean;
  isUnmappable: boolean;
}

interface ScrapeRun {
  job_id: string;
  run_date: string;
  final_count: number;
  new_count: number;
  returning_count: number;
  sources: string;
  completed_at: string;
}

interface MergeHistoryEntry {
  date: string;
  added_count: number;
  filename: string;
  previous_master: string;
  skills: string[];
  file_exists: boolean;
  file_size: string;
  job_id?: string | null;
  run_date?: string | null;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const PAGE_SIZE = 50;

const CHART_COLORS = [
  "#6366f1","#8b5cf6","#a78bfa","#c4b5fd","#ddd6fe",
  "#e0e7ff","#c7d2fe","#a5b4fc","#818cf8","#4f46e5",
  "#4338ca","#3730a3","#312e81","#1e1b4b","#07060f","#030207",
];

const ALL_CLASSIFICATIONS = [
  "Technical Skill","Tool","Functional Skill","Technical","Soft Skill",
  "Analytical","Functional","Power","AI","Strategic","Leadership","Cognitive","Green",
];

const getConfidenceBadgeClass = (score: number): string => {
  if (score >= 0.8) return "bg-green-100 text-green-700 border-green-200";
  if (score >= 0.6) return "bg-amber-100 text-amber-700 border-amber-200";
  return "bg-red-100 text-red-700 border-red-200";
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const TaxonomyManagerPage = () => {
  const [activeTab, setActiveTab] = useState<ActiveTab>("stats");

  // Overview pipeline
  const [overview, setOverview] = useState<OverviewData | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(false);
  const [overviewError, setOverviewError] = useState("");

  // Stats
  const [stats, setStats] = useState<TaxonomyStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [statsError, setStatsError] = useState("");

  // Compare
  const [compareResult, setCompareResult] = useState<CompareResult | null>(null);
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareError, setCompareError] = useState("");
  const [editedSkills, setEditedSkills] = useState<EditedSkill[]>([]);
  const [domainsIndex, setDomainsIndex] = useState<Record<string, string[]>>({});
  const [page, setPage] = useState(0);
  const [skillFilter, setSkillFilter] = useState<"all" | "mapped" | "unmappable">("all");
  const [mergeConfidenceThreshold, setMergeConfidenceThreshold] = useState(0.6);

  // Recent scrape runs (for per-run compare)
  const [runs, setRuns] = useState<ScrapeRun[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [runsError, setRunsError] = useState("");
  const [selectedRun, setSelectedRun] = useState<ScrapeRun | null>(null);
  const [deletingRunId, setDeletingRunId] = useState<string | null>(null);

  // Merged-skills viewer for completed runs
  const [mergedView, setMergedView] = useState<{ run: ScrapeRun; loading: boolean; skills: any[]; error: string } | null>(null);

  // Merge
  const [merging, setMerging] = useState(false);
  const [mergeResult, setMergeResult] = useState<{ job_id: string; filename: string; added_count: number; new_master: string } | null>(null);
  const [mergeError, setMergeError] = useState("");

  // History
  const [history, setHistory] = useState<MergeHistoryEntry[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [expandedEntry, setExpandedEntry] = useState<string | null>(null);

  // ---------------------------------------------------------------------------
  // Load on mount + tab switch
  // ---------------------------------------------------------------------------

  useEffect(() => {
    loadOverview();
  }, []);

  useEffect(() => {
    if (activeTab === "stats") loadStats();
    if (activeTab === "history") loadHistory();
    if (activeTab === "merge") {
      loadRuns();
      loadHistory();
    }
  }, [activeTab]);

  const loadOverview = async () => {
    setOverviewLoading(true);
    setOverviewError("");
    try {
      const res = await fetch(apiUrl("/api/taxonomy/overview"));
      if (!res.ok) throw new Error(`Server error ${res.status}`);
      setOverview(await res.json());
    } catch (e: any) {
      setOverviewError(e.message || "Failed to load overview");
    } finally {
      setOverviewLoading(false);
    }
  };

  const downloadNewSkills = (fmt: "csv" | "xlsx") => {
    if (!selectedRun) return;
    const url = `/api/taxonomy/new-skills/download?format=${fmt}&run_date=${encodeURIComponent(selectedRun.run_date)}&job_id=${encodeURIComponent(selectedRun.job_id)}`;
    window.open(apiUrl(url), "_blank");
  };

  const downloadMergedRun = (run: ScrapeRun, fmt: "csv" | "xlsx" = "xlsx") => {
    const url = `/api/taxonomy/new-skills/download?format=${fmt}&merged=true&run_date=${encodeURIComponent(run.run_date)}&job_id=${encodeURIComponent(run.job_id)}`;
    window.open(apiUrl(url), "_blank");
  };

  const viewMergedSkills = async (run: ScrapeRun) => {
    setSelectedRun(run);
    setMergedView({ run, loading: true, skills: [], error: "" });
    try {
      const res = await fetch(apiUrl(`/api/taxonomy/runs/${encodeURIComponent(run.job_id)}/merged-skills`));
      if (!res.ok) throw new Error(`Server error ${res.status}`);
      const data = await res.json();
      setMergedView({ run, loading: false, skills: data.skills || [], error: "" });
    } catch (e: any) {
      setMergedView({ run, loading: false, skills: [], error: e.message || "Failed to load merged skills" });
    }
  };

  const deleteRun = async (run: ScrapeRun) => {
    const ok = window.confirm(
      `Delete run ${run.run_date} (${run.final_count.toLocaleString()} skills)?\n\n` +
      `Removes:\n` +
      `  • the run record\n` +
      `  • skills only seen in this run\n` +
      `  • merge-history entries for this run\n\n` +
      `Keeps: gold taxonomy entries already merged from this run.\n\n` +
      `This cannot be undone.`
    );
    if (!ok) return;
    setDeletingRunId(run.job_id);
    try {
      const res = await fetch(apiUrl(`/api/taxonomy/runs/${encodeURIComponent(run.job_id)}`), { method: "DELETE" });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Server error ${res.status}`);
      }
      const result = await res.json();
      // Clear any view tied to this run
      if (selectedRun?.job_id === run.job_id) {
        setSelectedRun(null);
        setCompareResult(null);
        setEditedSkills([]);
        setMergedView(null);
      }
      await loadRuns();
      await loadHistory();
      await loadOverview();
      window.alert(
        `Run deleted.\n\n` +
        `Skills removed: ${result.skills_deleted}\n` +
        `Rejected removed: ${result.rejected_deleted}\n` +
        `Merge entries removed: ${result.merges_deleted}`
      );
    } catch (e: any) {
      window.alert(`Delete failed: ${e.message || e}`);
    } finally {
      setDeletingRunId(null);
    }
  };

  const loadRuns = async () => {
    setRunsLoading(true);
    setRunsError("");
    try {
      const res = await fetch(apiUrl("/api/taxonomy/runs?limit=10"));
      if (!res.ok) throw new Error(`Server error ${res.status}`);
      setRuns(await res.json());
    } catch (e: any) {
      setRunsError(e.message || "Failed to load scrape runs");
    } finally {
      setRunsLoading(false);
    }
  };

  const downloadFullTaxonomy = () => {
    window.open(apiUrl("/api/taxonomy/master/download"), "_blank");
  };

  const loadStats = async () => {
    setStatsLoading(true);
    setStatsError("");
    try {
      const res = await fetch(apiUrl("/api/taxonomy/stats"));
      if (!res.ok) throw new Error(`Server error ${res.status}`);
      setStats(await res.json());
    } catch (e: any) {
      setStatsError(e.message || "Failed to load stats");
    } finally {
      setStatsLoading(false);
    }
  };

  const loadHistory = async () => {
    setHistoryLoading(true);
    setHistoryError("");
    try {
      const res = await fetch(apiUrl("/api/taxonomy/history"));
      if (!res.ok) throw new Error(`Server error ${res.status}`);
      setHistory(await res.json());
    } catch (e: any) {
      setHistoryError(e.message || "Failed to load history");
    } finally {
      setHistoryLoading(false);
    }
  };

  const loadDomainsIndex = useCallback(async () => {
    if (Object.keys(domainsIndex).length > 0) return;
    try {
      const res = await fetch(apiUrl("/api/taxonomy/domains"));
      if (res.ok) setDomainsIndex(await res.json());
    } catch {}
  }, [domainsIndex]);

  // ---------------------------------------------------------------------------
  // Compare
  // ---------------------------------------------------------------------------

  const runCompare = async (run?: ScrapeRun) => {
    const target = run ?? selectedRun;
    if (!target) {
      setCompareError("Select a scrape run above to compare.");
      return;
    }
    setSelectedRun(target);
    setCompareLoading(true);
    setCompareError("");
    setCompareResult(null);
    setMergeResult(null);
    setMergeError("");
    setMergedView(null);
    setPage(0);
    await loadDomainsIndex();
    try {
      const qs = `?run_date=${encodeURIComponent(target.run_date)}&job_id=${encodeURIComponent(target.job_id)}`;
      const res = await fetch(apiUrl(`/api/taxonomy/compare${qs}`));
      if (!res.ok) throw new Error(`Server error ${res.status}`);
      const data: CompareResult = await res.json();
      setCompareResult(data);
      setEditedSkills([
        ...data.new_skills.map((s) => ({ ...s, selected: true, isUnmappable: false })),
        ...data.unmappable.map((s) => ({ ...s, selected: true, isUnmappable: true })),
      ]);
    } catch (e: any) {
      setCompareError(e.message || "Comparison failed");
    } finally {
      setCompareLoading(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Row editing
  // ---------------------------------------------------------------------------

  const toggleSelect = (idx: number) =>
    setEditedSkills((prev) => prev.map((s, i) => i === idx ? { ...s, selected: !s.selected } : s));

  const selectAll = () => setEditedSkills((prev) => prev.map((s) => ({ ...s, selected: true })));
  const deselectAll = () => setEditedSkills((prev) => prev.map((s) => ({ ...s, selected: false })));

  const updateField = (idx: number, field: keyof EditedSkill, value: string) => {
    setEditedSkills((prev) =>
      prev.map((s, i) => {
        if (i !== idx) return s;
        const updated = { ...s, [field]: value };
        if (field === "proposed_domain") {
          const firstSub = (domainsIndex[value] || [])[0] || "";
          updated.proposed_subdomain = firstSub;
          updated.proposed_cluster = firstSub;
        }
        if (field === "proposed_subdomain") updated.proposed_cluster = value;
        return updated;
      })
    );
  };

  // ---------------------------------------------------------------------------
  // Merge
  // ---------------------------------------------------------------------------

  const doMerge = async () => {
    const approved = editedSkills.filter((s) => s.selected);
    if (approved.length === 0) return;
    setMerging(true);
    setMergeError("");
    setMergeResult(null);
    try {
      const res = await fetch(apiUrl("/api/taxonomy/merge"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          approved_skills: approved,
          job_id: selectedRun?.job_id,
          run_date: selectedRun?.run_date,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Server error ${res.status}`);
      }
      const result = await res.json();
      setMergeResult(result);
      // Refresh stats + history so the run card flips to "Merged"
      setStats(null);
      loadStats();
      loadHistory();
    } catch (e: any) {
      setMergeError(e.message || "Merge failed");
    } finally {
      setMerging(false);
    }
  };

  const downloadMerged = () => {
    if (!mergeResult) return;
    window.open(apiUrl(`/api/taxonomy/download/${mergeResult.job_id}`), "_blank");
  };

  const downloadHistoryFile = (filename: string) => {
    window.open(apiUrl(`/api/taxonomy/history/${filename}/download`), "_blank");
  };

  // ---------------------------------------------------------------------------
  // Stats tab
  // ---------------------------------------------------------------------------

  const renderStats = () => {
    if (statsLoading) return (
      <div className="flex items-center justify-center h-48 text-muted-foreground">
        <RefreshCw className="w-5 h-5 animate-spin mr-2" /> Loading taxonomy…
      </div>
    );
    if (statsError) return (
      <div className="rounded-lg bg-destructive/10 text-destructive px-4 py-3 text-sm">{statsError}</div>
    );
    if (!stats) return null;

    const chartData = Object.entries(stats.domain_breakdown).map(([name, count]) => ({
      name: name.length > 22 ? name.slice(0, 22) + "…" : name,
      fullName: name,
      count,
    }));

    return (
      <div className="space-y-6">
        {/* Active master banner */}
        <div className={`flex items-center gap-3 rounded-lg px-4 py-3 text-sm border ${stats.is_original ? "bg-amber-50 border-amber-200 text-amber-800" : "bg-green-50 border-green-200 text-green-800"}`}>
          <FileCheck className="w-4 h-4 shrink-0" />
          <div>
            <span className="font-medium">Active master: </span>
            <code className="text-xs bg-white/60 px-1.5 py-0.5 rounded">{stats.master_filename}</code>
            {stats.is_original
              ? <span className="ml-2 text-amber-600">(original — no merges yet)</span>
              : <span className="ml-2 text-green-700">(updated after last merge)</span>}
          </div>
          <Button variant="outline" size="sm" className="ml-auto" onClick={loadStats}>
            <RefreshCw className="w-3 h-3 mr-1" /> Refresh
          </Button>
        </div>

        {/* Summary cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[
            { label: "Total Skills", value: stats.total_skills.toLocaleString(), icon: BookOpen },
            { label: "Domains", value: stats.domain_count, icon: FolderTree },
            { label: "Subdomains", value: stats.subdomain_count, icon: Layers },
            { label: "Skill Clusters", value: stats.skill_cluster_count.toLocaleString(), icon: Database },
          ].map(({ label, value, icon: Icon }) => (
            <Card key={label}>
              <CardContent className="pt-5 pb-4">
                <div className="flex items-center gap-2 text-muted-foreground mb-1">
                  <Icon className="w-4 h-4" />
                  <span className="text-xs">{label}</span>
                </div>
                <div className="text-2xl font-bold">{value}</div>
              </CardContent>
            </Card>
          ))}
        </div>

        {/* Domain chart */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Skills per Domain</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={chartData} layout="vertical" margin={{ left: 8, right: 24 }}>
                <XAxis type="number" tick={{ fontSize: 11 }} />
                <YAxis type="category" dataKey="name" width={180} tick={{ fontSize: 11 }} />
                <Tooltip formatter={(val: number, _: string, props: any) => [val.toLocaleString(), props.payload?.fullName || "Skills"]} />
                <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                  {chartData.map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        {/* Classification breakdown */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Skill Classification Breakdown</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {Object.entries(stats.classification_breakdown).map(([cls, cnt]) => (
                <Badge key={cls} variant="secondary" className="text-xs">
                  {cls}: {cnt.toLocaleString()}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Sheet breakdown */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Sheet Breakdown</CardTitle>
          </CardHeader>
          <CardContent className="flex gap-6 text-sm">
            <div><span className="text-muted-foreground">Final 16 Domains: </span><span className="font-semibold">{stats.sheet1_count.toLocaleString()}</span></div>
            <div><span className="text-muted-foreground">Domain Independent & Irrelevant: </span><span className="font-semibold">{stats.sheet2_count.toLocaleString()}</span></div>
          </CardContent>
        </Card>
      </div>
    );
  };

  // ---------------------------------------------------------------------------
  // Compare & Merge tab
  // ---------------------------------------------------------------------------

  const renderMerge = () => {
    // Build filtered list with original indices so toggleSelect/updateField stay correct
    const filteredWithIdx = editedSkills
      .map((s, idx) => ({ ...s, _idx: idx }))
      .filter((s) => {
        if (skillFilter === "mapped") return !s.isUnmappable;
        if (skillFilter === "unmappable") return s.isUnmappable;
        return true;
      });

    const totalFilteredPages = Math.ceil(filteredWithIdx.length / PAGE_SIZE);
    const pagedFilteredSkills = filteredWithIdx.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
    const selectedCount = editedSkills.filter((s) => s.selected).length;
    const mappedCount = editedSkills.filter((s) => !s.isUnmappable).length;
    const unmappableCount = editedSkills.filter((s) => s.isUnmappable).length;

    const step1Done = !!compareResult;
    const step2Done = !!mergeResult;

    return (
      <div className="space-y-6">
        {/* Step progress indicator */}
        <div className="flex items-center">
          {([
            { n: 1, label: "Compare", done: step1Done, active: !step2Done },
            { n: 2, label: "Review Skills", done: step2Done, active: step1Done && !step2Done },
            { n: 3, label: "Merge Complete", done: step2Done, active: step2Done },
          ] as { n: number; label: string; done: boolean; active: boolean }[]).map((step, i) => (
            <div key={step.n} className="flex items-center">
              <div className={`flex items-center gap-2 text-sm font-medium
                ${step.done ? "text-green-700" : step.active ? "text-primary" : "text-muted-foreground"}`}>
                <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold shrink-0
                  ${step.done ? "bg-green-500 text-white" : step.active ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"}`}>
                  {step.done && i < 2 ? "✓" : step.n}
                </div>
                <span className="hidden sm:inline">{step.label}</span>
              </div>
              {i < 2 && (
                <div className={`w-10 h-px mx-2 ${i === 0 && step1Done ? "bg-green-300" : "bg-border"}`} />
              )}
            </div>
          ))}
        </div>

        {/* ── POST-MERGE SUCCESS VIEW ── */}
        {mergeResult && (
          <div className="rounded-xl border-2 border-green-200 bg-green-50 p-6 space-y-4">
            <div className="flex items-center gap-3">
              <div className="w-12 h-12 rounded-full bg-green-100 flex items-center justify-center shrink-0">
                <FileCheck className="w-6 h-6 text-green-600" />
              </div>
              <div>
                <h3 className="font-semibold text-green-900 text-lg">Merge Complete</h3>
                <p className="text-sm text-green-700 mt-0.5">
                  {mergeResult.added_count.toLocaleString()} skills successfully added to master taxonomy
                </p>
              </div>
            </div>
            <div className="bg-white/70 rounded-lg p-3 text-xs space-y-1.5 border border-green-100">
              <div className="flex items-center gap-2">
                <span className="text-green-700 font-medium">New master file:</span>
                <code className="bg-green-100/60 px-1.5 py-0.5 rounded">{mergeResult.new_master}</code>
              </div>
              <p className="text-green-600">
                Future comparisons will automatically exclude skills already in this file.
              </p>
            </div>
            <div className="flex gap-2">
              <Button size="sm" onClick={downloadMerged}>
                <Download className="w-4 h-4 mr-2" />Download New Master
              </Button>
              <Button variant="outline" size="sm" onClick={() => selectedRun && runCompare(selectedRun)}>
                <RefreshCw className="w-4 h-4 mr-2" />Run New Comparison
              </Button>
            </div>
          </div>
        )}

        {/* ── COMPARE + REVIEW FLOW ── */}
        {!mergeResult && (
          <>
            {/* Recent scrape runs */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold">Recent scrape runs</h3>
                <Button variant="ghost" size="sm" onClick={loadRuns} disabled={runsLoading}>
                  <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${runsLoading ? "animate-spin" : ""}`} />
                  Refresh
                </Button>
              </div>
              {runsError && <div className="text-sm text-red-600">{runsError}</div>}
              {runsLoading && runs.length === 0 && (
                <div className="text-sm text-muted-foreground">Loading runs…</div>
              )}
              {!runsLoading && runs.length === 0 && !runsError && (
                <div className="text-sm text-muted-foreground">No scrape runs found yet.</div>
              )}
              <div className="flex gap-3 overflow-x-auto pb-2">
                {runs.map((r) => {
                  const isSelected = selectedRun?.job_id === r.job_id;
                  const dateLabel = r.run_date;
                  const timeLabel = (() => {
                    try { return new Date(r.completed_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }
                    catch { return ""; }
                  })();
                  const mergedEntry = history.find(
                    (h) => (h.job_id && h.job_id === r.job_id) || (!h.job_id && h.run_date === r.run_date)
                  );
                  const isMerged = !!mergedEntry;
                  const isDeleting = deletingRunId === r.job_id;
                  const onCardActivate = () => {
                    if (isDeleting) return;
                    if (isMerged) viewMergedSkills(r);
                    else runCompare(r);
                  };
                  return (
                    <div
                      key={r.job_id}
                      role="button"
                      tabIndex={0}
                      onClick={onCardActivate}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onCardActivate(); }
                      }}
                      className={`relative shrink-0 w-72 border rounded-lg p-3 space-y-2 transition cursor-pointer hover:shadow-sm
                        ${isMerged ? "border-green-300 bg-green-50/50 hover:bg-green-50"
                          : isSelected ? "border-primary bg-primary/5"
                          : "border-border bg-card hover:border-muted-foreground/40"}
                        ${isDeleting ? "opacity-50 pointer-events-none" : ""}`}
                    >
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); deleteRun(r); }}
                        disabled={isDeleting}
                        title="Delete this run"
                        aria-label="Delete this run"
                        className="absolute top-2 right-2 p-1 rounded text-muted-foreground hover:text-red-600 hover:bg-red-50"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                      <div className="flex items-center justify-between text-xs pr-6">
                        <span className="font-medium">{dateLabel}</span>
                        {timeLabel && <span className="text-muted-foreground">{timeLabel}</span>}
                      </div>
                      <div className="flex flex-wrap gap-1.5 text-xs">
                        <Badge variant="secondary">{r.final_count.toLocaleString()} skills</Badge>
                        {isMerged ? (
                          <Badge className="bg-green-600 hover:bg-green-600">
                            <FileCheck className="w-3 h-3 mr-1" />
                            Merged · {mergedEntry!.added_count.toLocaleString()}
                          </Badge>
                        ) : (
                          <Badge variant="outline" className="border-green-300 text-green-700">
                            {r.new_count.toLocaleString()} new
                          </Badge>
                        )}
                      </div>
                      {r.sources && (
                        <div className="text-[11px] text-muted-foreground truncate" title={r.sources}>
                          {r.sources}
                        </div>
                      )}
                      {isMerged ? (
                        <div className="flex gap-1.5" onClick={(e) => e.stopPropagation()}>
                          <Button size="sm" variant="outline" className="flex-1" onClick={() => downloadMergedRun(r, "xlsx")}>
                            <Download className="w-3.5 h-3.5 mr-1.5" />XLSX
                          </Button>
                          <Button size="sm" variant="outline" className="flex-1" onClick={() => downloadMergedRun(r, "csv")}>
                            <Download className="w-3.5 h-3.5 mr-1.5" />CSV
                          </Button>
                        </div>
                      ) : (
                        <Button
                          size="sm"
                          variant={isSelected && compareResult ? "outline" : "default"}
                          className="w-full"
                          onClick={(e) => { e.stopPropagation(); runCompare(r); }}
                          disabled={compareLoading || merging}
                        >
                          {compareLoading && isSelected
                            ? <><RefreshCw className="w-3.5 h-3.5 mr-1.5 animate-spin" />Comparing…</>
                            : isSelected && compareResult
                              ? <><RefreshCw className="w-3.5 h-3.5 mr-1.5" />Re-compare</>
                              : <><RefreshCw className="w-3.5 h-3.5 mr-1.5" />Compare</>}
                        </Button>
                      )}
                    </div>
                  );
                })}
              </div>
              {!compareResult && !compareLoading && !mergedView && (
                <p className="text-xs text-muted-foreground">
                  Click a run card to view its skills. Unmerged runs run a fresh compare; merged runs show what landed in gold.
                </p>
              )}
            </div>

            {/* Merged-run skills viewer (read-only) */}
            {mergedView && (
              <Card className="border-green-200">
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between gap-2 flex-wrap">
                    <CardTitle className="text-base flex items-center gap-2">
                      <FileCheck className="w-4 h-4 text-green-600" />
                      Merged skills · run {mergedView.run.run_date}
                      {!mergedView.loading && <Badge variant="secondary">{mergedView.skills.length}</Badge>}
                    </CardTitle>
                    <div className="flex items-center gap-2">
                      <Button size="sm" variant="outline" onClick={() => downloadMergedRun(mergedView.run, "xlsx")}>
                        <Download className="w-3.5 h-3.5 mr-1.5" />XLSX
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => downloadMergedRun(mergedView.run, "csv")}>
                        <Download className="w-3.5 h-3.5 mr-1.5" />CSV
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setMergedView(null)} aria-label="Close">
                        <X className="w-4 h-4" />
                      </Button>
                    </div>
                  </div>
                </CardHeader>
                <CardContent>
                  {mergedView.loading && <div className="text-sm text-muted-foreground">Loading…</div>}
                  {mergedView.error && <div className="text-sm text-red-600">{mergedView.error}</div>}
                  {!mergedView.loading && !mergedView.error && mergedView.skills.length === 0 && (
                    <div className="text-sm text-muted-foreground">No merged skills found for this run.</div>
                  )}
                  {!mergedView.loading && mergedView.skills.length > 0 && (
                    <div className="max-h-[420px] overflow-y-auto border rounded">
                      <Table>
                        <TableHeader className="sticky top-0 bg-background z-10">
                          <TableRow>
                            <TableHead>Skill Name</TableHead>
                            <TableHead>Domain</TableHead>
                            <TableHead>Subdomain</TableHead>
                            <TableHead>Source</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {mergedView.skills.map((s, i) => (
                            <TableRow key={i}>
                              <TableCell className="font-medium">{s.skill_name}</TableCell>
                              <TableCell className="text-xs">{s.taxonomy_domain || "—"}</TableCell>
                              <TableCell className="text-xs">{s.taxonomy_subdomain || "—"}</TableCell>
                              <TableCell className="text-xs text-muted-foreground">{s.source || "—"}</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  )}
                </CardContent>
              </Card>
            )}

            {/* Run-scoped download buttons */}
            {compareResult && selectedRun && (
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm text-muted-foreground">
                  Run <code className="bg-muted/60 px-1.5 py-0.5 rounded text-xs">{selectedRun.run_date}</code>:
                </span>
                <Button variant="outline" size="sm" onClick={() => downloadNewSkills("xlsx")}>
                  <Download className="w-4 h-4 mr-2" />New skills (XLSX)
                </Button>
                <Button variant="outline" size="sm" onClick={() => downloadNewSkills("csv")}>
                  <Download className="w-4 h-4 mr-2" />New skills (CSV)
                </Button>
              </div>
            )}

            {compareError && (
              <div className="rounded-lg bg-destructive/10 text-destructive px-4 py-3 text-sm">{compareError}</div>
            )}

            {/* Empty state */}
            {!compareResult && !compareLoading && !compareError && (
              <div className="flex flex-col items-center justify-center py-16 gap-4 border-2 border-dashed border-border rounded-xl text-center">
                <div className="w-14 h-14 rounded-2xl bg-muted flex items-center justify-center">
                  <GitMerge className="w-7 h-7 text-muted-foreground" />
                </div>
                <div>
                  <h3 className="font-semibold mb-1">No comparison run yet</h3>
                  <p className="text-sm text-muted-foreground max-w-xs">
                    Run a comparison to find new skills scraped since the last master update.
                  </p>
                </div>
              </div>
            )}

            {compareResult && (
              <>
                {/* Summary cards */}
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                  {[
                    { label: "DB Skills", value: compareResult.total_db_skills, color: "" },
                    { label: "Already in Master", value: compareResult.matched, color: "text-green-600" },
                    { label: "Auto-classified", value: compareResult.new_skills.length, color: "text-blue-600" },
                    {
                      label: "Needs Review",
                      value: compareResult.unmappable.length,
                      color: compareResult.unmappable.length > 0 ? "text-amber-600" : "text-muted-foreground",
                    },
                  ].map(({ label, value, color }) => (
                    <Card key={label}>
                      <CardContent className="pt-5 pb-4">
                        <div className="text-xs text-muted-foreground mb-1">{label}</div>
                        <div className={`text-2xl font-bold ${color}`}>{value.toLocaleString()}</div>
                      </CardContent>
                    </Card>
                  ))}
                </div>

                {mergeError && (
                  <div className="rounded-lg bg-destructive/10 text-destructive px-4 py-3 text-sm">{mergeError}</div>
                )}

                {/* Unified skills table with filter tabs */}
                {editedSkills.length > 0 && (
                  <Card>
                    <CardHeader className="pb-3">
                      <div className="flex items-center justify-between gap-4 flex-wrap">
                        <CardTitle className="text-sm font-medium">Review Skills to Add</CardTitle>
                        {/* Filter tabs */}
                        <div className="flex items-center gap-1 border rounded-lg p-1 bg-muted/30">
                          {([
                            { id: "all" as const, label: "All", count: editedSkills.length },
                            { id: "mapped" as const, label: "Auto-classified", count: mappedCount },
                            { id: "unmappable" as const, label: "Needs Review", count: unmappableCount },
                          ]).map((tab) => (
                            <button
                              key={tab.id}
                              onClick={() => { setSkillFilter(tab.id); setPage(0); }}
                              className={`px-3 py-1 rounded-md text-xs font-medium transition-colors flex items-center gap-1.5
                                ${skillFilter === tab.id
                                  ? "bg-background shadow-sm text-foreground"
                                  : "text-muted-foreground hover:text-foreground"}`}
                            >
                              {tab.label}
                              {tab.count > 0 && (
                                <span className={`px-1.5 py-0.5 rounded-full text-xs
                                  ${tab.id === "unmappable"
                                    ? "bg-amber-100 text-amber-700"
                                    : skillFilter === tab.id
                                      ? "bg-primary/10 text-primary"
                                      : "bg-muted text-muted-foreground"}`}>
                                  {tab.count}
                                </span>
                              )}
                            </button>
                          ))}
                        </div>
                      </div>
                    </CardHeader>
                    <CardContent className="p-0">
                      <div className="overflow-x-auto">
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead className="w-10"></TableHead>
                              <TableHead>Skill Name</TableHead>
                              <TableHead>Domain</TableHead>
                              <TableHead>Subdomain</TableHead>
                              <TableHead>Classification</TableHead>
                              <TableHead>Confidence</TableHead>
                              <TableHead>Source</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {pagedFilteredSkills.map((skill) => {
                              const absIdx = skill._idx;
                              const subdomains = domainsIndex[skill.proposed_domain] || [];
                              return (
                                <TableRow
                                  key={skill.db_id}
                                  className={`${skill.selected ? "" : "opacity-40"} ${skill.isUnmappable ? "bg-amber-50/50" : ""}`}
                                >
                                  <TableCell>
                                    <Checkbox checked={skill.selected} onCheckedChange={() => toggleSelect(absIdx)} />
                                  </TableCell>
                                  <TableCell>
                                    <div className="flex flex-col gap-1 min-w-[160px]">
                                      <span className="font-medium text-sm">{skill.skill_name}</span>
                                      {skill.isUnmappable && (
                                        <span className="inline-flex items-center text-[10px] font-medium text-amber-700 bg-amber-100 border border-amber-200 rounded px-1.5 py-0.5 w-fit">
                                          Needs Review
                                        </span>
                                      )}
                                    </div>
                                  </TableCell>
                                  <TableCell>
                                    <Select value={skill.proposed_domain} onValueChange={(v) => updateField(absIdx, "proposed_domain", v)}>
                                      <SelectTrigger className="h-7 text-xs w-44"><SelectValue /></SelectTrigger>
                                      <SelectContent>
                                        {Object.keys(domainsIndex).map((d) => (
                                          <SelectItem key={d} value={d} className="text-xs">{d}</SelectItem>
                                        ))}
                                      </SelectContent>
                                    </Select>
                                  </TableCell>
                                  <TableCell>
                                    <Select value={skill.proposed_subdomain} onValueChange={(v) => updateField(absIdx, "proposed_subdomain", v)}>
                                      <SelectTrigger className="h-7 text-xs w-44"><SelectValue /></SelectTrigger>
                                      <SelectContent>
                                        {subdomains.map((s) => (
                                          <SelectItem key={s} value={s} className="text-xs">{s}</SelectItem>
                                        ))}
                                      </SelectContent>
                                    </Select>
                                  </TableCell>
                                  <TableCell>
                                    <Select value={skill.proposed_classification} onValueChange={(v) => updateField(absIdx, "proposed_classification", v)}>
                                      <SelectTrigger className="h-7 text-xs w-36"><SelectValue /></SelectTrigger>
                                      <SelectContent>
                                        {ALL_CLASSIFICATIONS.map((c) => (
                                          <SelectItem key={c} value={c} className="text-xs">{c}</SelectItem>
                                        ))}
                                      </SelectContent>
                                    </Select>
                                  </TableCell>
                                  <TableCell>
                                    <Badge
                                      variant="outline"
                                      className={`text-xs ${getConfidenceBadgeClass(skill.confidence_score)}`}
                                    >
                                      {(skill.confidence_score * 100).toFixed(0)}%
                                    </Badge>
                                  </TableCell>
                                  <TableCell className="text-xs text-muted-foreground max-w-[160px] truncate">
                                    {skill.source}
                                  </TableCell>
                                </TableRow>
                              );
                            })}
                          </TableBody>
                        </Table>
                      </div>

                      {totalFilteredPages > 1 && (
                        <div className="flex items-center justify-between px-4 py-3 border-t text-sm text-muted-foreground">
                          <span>
                            Showing {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, filteredWithIdx.length)} of {filteredWithIdx.length.toLocaleString()}
                          </span>
                          <div className="flex gap-2">
                            <Button variant="outline" size="sm" disabled={page === 0} onClick={() => setPage(p => p - 1)}>Previous</Button>
                            <Button variant="outline" size="sm" disabled={page >= totalFilteredPages - 1} onClick={() => setPage(p => p + 1)}>Next</Button>
                          </div>
                        </div>
                      )}

                      {/* Action bar — always visible at the bottom of the table */}
                      <div className="border-t bg-muted/20 px-4 py-3 space-y-3">
                        {/* Confidence threshold row */}
                        <div className="flex items-center gap-3">
                          <span className="text-xs text-muted-foreground whitespace-nowrap">
                            Min confidence:
                            <span className="font-semibold text-foreground ml-1">
                              {(mergeConfidenceThreshold * 100).toFixed(0)}%
                            </span>
                          </span>
                          <div className="w-36">
                            <Slider
                              value={[mergeConfidenceThreshold]}
                              onValueChange={([v]) => {
                                setMergeConfidenceThreshold(v);
                                setEditedSkills(prev =>
                                  prev.map(s => ({ ...s, selected: s.confidence_score >= v }))
                                );
                              }}
                              min={0}
                              max={1}
                              step={0.05}
                            />
                          </div>
                          <div className="flex gap-1 text-xs text-muted-foreground">
                            {[0.4, 0.6, 0.8].map(preset => (
                              <button
                                key={preset}
                                onClick={() => {
                                  setMergeConfidenceThreshold(preset);
                                  setEditedSkills(prev =>
                                    prev.map(s => ({ ...s, selected: s.confidence_score >= preset }))
                                  );
                                }}
                                className={`px-2 py-0.5 rounded border text-xs transition-colors
                                  ${mergeConfidenceThreshold === preset
                                    ? "bg-primary text-primary-foreground border-primary"
                                    : "border-border hover:border-muted-foreground"}`}
                              >
                                {(preset * 100).toFixed(0)}%
                              </button>
                            ))}
                          </div>
                        </div>
                        {/* Select controls + merge button row */}
                        <div className="flex items-center gap-3 flex-wrap">
                          <span className="text-sm text-muted-foreground">
                            <span className="font-medium text-foreground">{selectedCount.toLocaleString()}</span> of {editedSkills.length.toLocaleString()} selected
                          </span>
                          <Button variant="outline" size="sm" onClick={selectAll}>Select All</Button>
                          <Button variant="outline" size="sm" onClick={deselectAll}>Deselect All</Button>
                          <div className="ml-auto">
                            <Button onClick={doMerge} disabled={merging || selectedCount === 0}>
                              {merging
                                ? <><RefreshCw className="w-4 h-4 mr-2 animate-spin" />Merging…</>
                                : <><GitMerge className="w-4 h-4 mr-2" />Merge {selectedCount > 0 ? `${selectedCount.toLocaleString()} Skills` : ""}</>}
                            </Button>
                          </div>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                )}
              </>
            )}
          </>
        )}
      </div>
    );
  };

  // ---------------------------------------------------------------------------
  // History tab
  // ---------------------------------------------------------------------------

  const renderHistory = () => {
    if (historyLoading) return (
      <div className="flex items-center justify-center h-48 text-muted-foreground">
        <RefreshCw className="w-5 h-5 animate-spin mr-2" /> Loading history…
      </div>
    );
    if (historyError) return (
      <div className="rounded-lg bg-destructive/10 text-destructive px-4 py-3 text-sm">{historyError}</div>
    );
    if (history.length === 0) return (
      <div className="flex flex-col items-center justify-center h-48 text-muted-foreground gap-2">
        <History className="w-8 h-8 opacity-30" />
        <p className="text-sm">No merges yet. Run a comparison and merge skills to build history.</p>
      </div>
    );

    const totalAdded = history.reduce((sum, e) => sum + e.added_count, 0);

    return (
      <div className="space-y-6">
        {/* Summary */}
        <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
          <Card>
            <CardContent className="pt-5 pb-4">
              <div className="text-xs text-muted-foreground mb-1">Total Merge Runs</div>
              <div className="text-2xl font-bold">{history.length}</div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-5 pb-4">
              <div className="text-xs text-muted-foreground mb-1">Total Skills Added</div>
              <div className="text-2xl font-bold text-green-600">{totalAdded.toLocaleString()}</div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-5 pb-4">
              <div className="text-xs text-muted-foreground mb-1">Last Merge</div>
              <div className="text-2xl font-bold">{history[0]?.date || "—"}</div>
            </CardContent>
          </Card>
        </div>

        {/* History list */}
        <div className="space-y-3">
          {history.map((entry) => {
            const isExpanded = expandedEntry === entry.filename;
            return (
              <Card key={entry.filename}>
                <CardContent className="pt-4 pb-4">
                  <div className="flex items-center justify-between gap-4">
                    <div className="flex items-center gap-3 min-w-0">
                      <div className="flex-shrink-0 w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center">
                        <GitMerge className="w-4 h-4 text-primary" />
                      </div>
                      <div className="min-w-0">
                        <div className="font-medium text-sm">{entry.date}</div>
                        <div className="text-xs text-muted-foreground truncate">
                          {entry.filename}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          Previous master: <code>{entry.previous_master}</code>
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-3 shrink-0">
                      <Badge className="bg-green-100 text-green-800 border-green-200">
                        +{entry.added_count.toLocaleString()} skills
                      </Badge>
                      {entry.file_size && (
                        <span className="text-xs text-muted-foreground">{entry.file_size}</span>
                      )}
                      {entry.file_exists && (
                        <Button variant="outline" size="sm" onClick={() => downloadHistoryFile(entry.filename)}>
                          <Download className="w-3 h-3 mr-1" />Download
                        </Button>
                      )}
                      <button
                        className="text-muted-foreground hover:text-foreground transition-colors"
                        onClick={() => setExpandedEntry(isExpanded ? null : entry.filename)}
                      >
                        {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                      </button>
                    </div>
                  </div>

                  {isExpanded && (
                    <div className="mt-4 pt-4 border-t">
                      <p className="text-xs font-medium text-muted-foreground mb-2">
                        Skills added in this merge ({entry.skills.length.toLocaleString()}):
                      </p>
                      <div className="flex flex-wrap gap-1.5 max-h-48 overflow-y-auto">
                        {entry.skills.map((skill) => (
                          <Badge key={skill} variant="secondary" className="text-xs font-normal">
                            {skill}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>
    );
  };

  // ---------------------------------------------------------------------------
  // Main render
  // ---------------------------------------------------------------------------

  // ---------------------------------------------------------------------------
  // Overview pipeline card
  // ---------------------------------------------------------------------------

  const renderOverview = () => {
    if (overviewLoading) return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground px-1">
        <RefreshCw className="w-4 h-4 animate-spin" /> Loading pipeline stats…
      </div>
    );
    if (overviewError) return (
      <div className="rounded-lg bg-destructive/10 text-destructive px-4 py-3 text-sm">{overviewError}</div>
    );
    if (!overview) return null;

    const steps = [
      { label: "In Taxonomy", value: overview.taxonomy_size.toLocaleString(), color: "text-indigo-600", bg: "bg-indigo-50 border-indigo-200" },
      { label: "Scraped", value: overview.scraped_count.toLocaleString(), color: "text-amber-600", bg: "bg-amber-50 border-amber-200" },
      { label: "New Found", value: overview.new_skills_count.toLocaleString(), color: "text-emerald-600", bg: "bg-emerald-50 border-emerald-200" },
    ];

    return (
      <Card className="p-4">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          {/* Pipeline steps */}
          <div className="flex items-center gap-2 flex-wrap">
            {steps.map((step, i) => (
              <div key={step.label} className="flex items-center gap-2">
                <div className={`rounded-lg border px-4 py-2.5 text-center min-w-[110px] ${step.bg}`}>
                  <div className={`text-xl font-bold ${step.color}`}>{step.value}</div>
                  <div className="text-xs text-muted-foreground mt-0.5">{step.label}</div>
                </div>
                {i < steps.length - 1 && <ArrowRight className="w-4 h-4 text-muted-foreground shrink-0" />}
              </div>
            ))}
          </div>

          {/* Download buttons */}
          <div className="flex items-center gap-2 flex-wrap">
            <Button variant="outline" size="sm" onClick={downloadFullTaxonomy}>
              <Download className="w-3.5 h-3.5 mr-1.5" />Full Taxonomy
            </Button>
          </div>
        </div>
      </Card>
    );
  };

  return (
    <div className="space-y-6">
      {renderOverview()}
      <div className="flex gap-1 border-b">
        {([
          { id: "stats", label: "Taxonomy Stats" },
          { id: "merge", label: "Compare & Merge" },
          { id: "history", label: "Merge History" },
        ] as { id: ActiveTab; label: string }[]).map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px ${
              activeTab === tab.id
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "stats" && renderStats()}
      {activeTab === "merge" && renderMerge()}
      {activeTab === "history" && renderHistory()}
    </div>
  );
};

export default TaxonomyManagerPage;
