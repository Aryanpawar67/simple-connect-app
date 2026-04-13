import { useState, useMemo } from "react";
import {
  Play,
  Download,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  FileSpreadsheet,
  CalendarRange,
  CalendarDays,
  Database,
  History,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

type FilterMode = "all" | "specific" | "range";
type RunState = "idle" | "loading" | "success" | "empty" | "error";

const MONTH_NAMES = [
  "January","February","March","April","May","June",
  "July","August","September","October","November","December",
];

function parseMonth(m: string): { year: string; month: string } | null {
  const match = m.trim().match(/^(\d{4})-(0[1-9]|1[0-2])$/);
  if (!match) return null;
  return { year: match[1], month: match[2] };
}

function formatMonth(m: string): string {
  const parsed = parseMonth(m);
  if (!parsed) return m;
  return `${MONTH_NAMES[parseInt(parsed.month) - 1]} ${parsed.year}`;
}

function generateFilename(mode: FilterMode, months: string, start: string, end: string): string {
  const base = "Lightcast_Skills_Taxonomy_Changelog";
  if (mode === "all") return `${base}_Full.xlsx`;
  if (mode === "specific") {
    const parts = months.split(",").map((m) => m.trim()).filter(Boolean);
    if (parts.length === 0) return "";
    const formatted = parts.map(formatMonth).join("_").replace(/ /g, "_");
    return `${base}_${formatted}.xlsx`;
  }
  if (mode === "range") {
    const s = parseMonth(start);
    const e = parseMonth(end);
    if (!s || !e) return "";
    const sf = formatMonth(start).replace(/ /g, "");
    const ef = formatMonth(end).replace(/ /g, "");
    return `${base}_${sf}_to_${ef}.xlsx`;
  }
  return "";
}

const PROGRESS_STEPS = [
  "Launching browser…",
  "Fetching changelog page…",
  "Parsing sections…",
  "Applying date filter…",
  "Exporting to Excel…",
];

const MOCK_EXPORT_HISTORY = [
  { date: "2026-04-10", filename: "Lightcast_Skills_Taxonomy_Changelog_Full.xlsx", records: 342, matched: 342, fileSize: "184 KB", filter: "All Data" },
  { date: "2026-03-15", filename: "Lightcast_Skills_Taxonomy_Changelog_March_2026.xlsx", records: 342, matched: 58, fileSize: "42 KB", filter: "March 2026" },
  { date: "2026-02-28", filename: "Lightcast_Skills_Taxonomy_Changelog_January_to_February_2026.xlsx", records: 310, matched: 97, fileSize: "68 KB", filter: "Jan–Feb 2026" },
  { date: "2026-02-01", filename: "Lightcast_Skills_Taxonomy_Changelog_February_2026.xlsx", records: 310, matched: 41, fileSize: "34 KB", filter: "February 2026" },
  { date: "2026-01-12", filename: "Lightcast_Skills_Taxonomy_Changelog_Full.xlsx", records: 278, matched: 278, fileSize: "156 KB", filter: "All Data" },
];

type ActiveTab = "run" | "history";

const ChangelogScraperPage = () => {
  const [activeTab, setActiveTab] = useState<ActiveTab>("run");
  const [filterMode, setFilterMode] = useState<FilterMode>("all");
  const [months, setMonths] = useState("");
  const [startMonth, setStartMonth] = useState("");
  const [endMonth, setEndMonth] = useState("");
  const [runState, setRunState] = useState<RunState>("idle");
  const [progressStep, setProgressStep] = useState(0);

  // Validation
  const monthsError = useMemo(() => {
    if (filterMode !== "specific" || !months.trim()) return "";
    const parts = months.split(",").map((m) => m.trim()).filter(Boolean);
    for (const p of parts) {
      if (!parseMonth(p)) return `Invalid format: "${p}". Use YYYY-MM (e.g. 2025-11)`;
    }
    return "";
  }, [filterMode, months]);

  const rangeError = useMemo(() => {
    if (filterMode !== "range") return "";
    if (startMonth && !parseMonth(startMonth)) return "Start: Use YYYY-MM format";
    if (endMonth && !parseMonth(endMonth)) return "End: Use YYYY-MM format";
    if (startMonth && endMonth && startMonth > endMonth) return "End must be on or after Start";
    return "";
  }, [filterMode, startMonth, endMonth]);

  const isValid = useMemo(() => {
    if (filterMode === "all") return true;
    if (filterMode === "specific") return months.trim() !== "" && !monthsError;
    if (filterMode === "range") return startMonth !== "" && endMonth !== "" && !rangeError;
    return false;
  }, [filterMode, months, monthsError, startMonth, endMonth, rangeError]);

  const filename = generateFilename(filterMode, months, startMonth, endMonth);

  const simulateRun = async () => {
    setRunState("loading");
    for (let i = 0; i < PROGRESS_STEPS.length; i++) {
      setProgressStep(i);
      await new Promise((r) => setTimeout(r, 700 + Math.random() * 800));
    }
    setRunState("success");
  };

  return (
    <div className="max-w-3xl mx-auto space-y-6 animate-fade-in">
      {/* Tab Switcher */}
      <div className="flex gap-1 bg-secondary rounded-xl p-1">
        {[
          { id: "run" as ActiveTab, label: "Run Export", icon: Play },
          { id: "history" as ActiveTab, label: "History", icon: History },
        ].map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-all",
                activeTab === tab.id
                  ? "bg-card text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              <Icon className="w-4 h-4" />
              {tab.label}
            </button>
          );
        })}
      </div>

      {activeTab === "run" && (<>
      {/* Filter Mode */}
      <Card className="p-6">
        <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-4">
          Filter Mode
        </h3>
        <div className="grid grid-cols-3 gap-3">
          {[
            { id: "all" as const, label: "All Data", desc: "Full changelog", icon: Database },
            { id: "specific" as const, label: "Specific Months", desc: "Pick months", icon: CalendarDays },
            { id: "range" as const, label: "Date Range", desc: "Start → End", icon: CalendarRange },
          ].map((opt) => {
            const Icon = opt.icon;
            return (
              <button
                key={opt.id}
                onClick={() => setFilterMode(opt.id)}
                className={cn(
                  "flex flex-col items-center gap-2 p-4 rounded-xl border-2 transition-all text-center",
                  filterMode === opt.id
                    ? "border-primary bg-primary/5"
                    : "border-border hover:border-muted-foreground/30"
                )}
              >
                <Icon className={cn("w-5 h-5", filterMode === opt.id ? "text-primary" : "text-muted-foreground")} />
                <div>
                  <div className="text-sm font-medium">{opt.label}</div>
                  <div className="text-xs text-muted-foreground">{opt.desc}</div>
                </div>
              </button>
            );
          })}
        </div>
      </Card>

      {/* Conditional inputs */}
      {filterMode === "specific" && (
        <Card className="p-6 animate-slide-up">
          <label className="text-sm font-medium block mb-2">
            Month(s) <span className="text-muted-foreground font-normal">— comma-separated, YYYY-MM</span>
          </label>
          <Input
            placeholder="e.g. 2025-11, 2025-12"
            value={months}
            onChange={(e) => setMonths(e.target.value)}
          />
          {monthsError && (
            <p className="text-sm text-destructive mt-2 flex items-center gap-1">
              <AlertTriangle className="w-3.5 h-3.5" />
              {monthsError}
            </p>
          )}
        </Card>
      )}

      {filterMode === "range" && (
        <Card className="p-6 animate-slide-up">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium block mb-2">Start Month</label>
              <Input
                placeholder="YYYY-MM"
                value={startMonth}
                onChange={(e) => setStartMonth(e.target.value)}
              />
            </div>
            <div>
              <label className="text-sm font-medium block mb-2">End Month</label>
              <Input
                placeholder="YYYY-MM"
                value={endMonth}
                onChange={(e) => setEndMonth(e.target.value)}
              />
            </div>
          </div>
          {rangeError && (
            <p className="text-sm text-destructive mt-3 flex items-center gap-1">
              <AlertTriangle className="w-3.5 h-3.5" />
              {rangeError}
            </p>
          )}
        </Card>
      )}

      {/* Filename Preview */}
      {isValid && filename && (
        <Card className="p-4 bg-secondary/50 animate-slide-up">
          <div className="flex items-center gap-2 text-sm">
            <FileSpreadsheet className="w-4 h-4 text-muted-foreground" />
            <span className="text-muted-foreground">Output:</span>
            <code className="font-mono text-xs bg-background px-2 py-1 rounded border">{filename}</code>
          </div>
        </Card>
      )}

      {/* Run Button */}
      <Button
        size="lg"
        onClick={simulateRun}
        disabled={!isValid || runState === "loading"}
        className="w-full h-12 text-base font-semibold"
      >
        {runState === "loading" ? (
          <>
            <Loader2 className="w-5 h-5 mr-2 animate-spin" />
            {PROGRESS_STEPS[progressStep]}
          </>
        ) : (
          <>
            <Play className="w-5 h-5 mr-2" />
            Run Scraper
          </>
        )}
      </Button>

      {/* Progress steps */}
      {runState === "loading" && (
        <Card className="p-6 animate-slide-up">
          <div className="space-y-2">
            {PROGRESS_STEPS.map((step, i) => (
              <div key={step} className="flex items-center gap-2 text-sm">
                {i < progressStep ? (
                  <CheckCircle2 className="w-4 h-4 text-success" />
                ) : i === progressStep ? (
                  <Loader2 className="w-4 h-4 text-primary animate-spin" />
                ) : (
                  <div className="w-4 h-4 rounded-full border-2 border-muted" />
                )}
                <span className={cn(i > progressStep && "text-muted-foreground")}>{step}</span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Success */}
      {runState === "success" && (
        <Card className="p-6 border-success/30 bg-success/5 animate-slide-up">
          <div className="flex items-start justify-between">
            <div>
              <h3 className="font-semibold flex items-center gap-2">
                <CheckCircle2 className="w-5 h-5 text-success" />
                Export Complete
              </h3>
              <p className="text-sm text-muted-foreground mt-1">
                342 records found · 287 match your filter
              </p>
              <div className="flex gap-2 mt-2">
                <Badge variant="secondary">Added: 45</Badge>
                <Badge variant="secondary">Removed: 12</Badge>
                <Badge variant="secondary">Renamed: 8</Badge>
                <Badge variant="secondary">Consolidated: 3</Badge>
              </div>
            </div>
            <Button variant="outline" size="sm">
              <Download className="w-4 h-4 mr-1.5" />
              {filename || "Download"}
            </Button>
          </div>
        </Card>
      )}
    </div>
  );
};

export default ChangelogScraperPage;
