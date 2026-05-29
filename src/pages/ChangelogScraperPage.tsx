import { useState, useMemo, useRef, useEffect } from "react";
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
import { apiUrl } from "@/lib/api";
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
  "Enriching descriptions…",
  "Exporting to Excel…",
];

type HistoryEntry = {
  date: string;
  filename: string;
  filter: string;
  totalRecords: number;
  matchedRecords: number;
  fileSize: string;
};

type ActiveTab = "run" | "history";

const ChangelogScraperPage = () => {
  const [activeTab, setActiveTab] = useState<ActiveTab>("run");
  const [filterMode, setFilterMode] = useState<FilterMode>("all");
  const [months, setMonths] = useState("");
  const [startMonth, setStartMonth] = useState("");
  const [endMonth, setEndMonth] = useState("");
  const [runState, setRunState] = useState<RunState>("idle");
  const [progressStep, setProgressStep] = useState(0);
  const [jobId, setJobId] = useState<string | null>(null);
  const [totalRecords, setTotalRecords] = useState(0);
  const [matchedRecords, setMatchedRecords] = useState(0);
  const [typeCounts, setTypeCounts] = useState<Record<string, number>>({});
  const [errorMessage, setErrorMessage] = useState("");
  const esRef = useRef<EventSource | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  useEffect(() => {
    if (activeTab !== "history") return;
    setHistoryLoading(true);
    fetch(apiUrl("/api/changelog/history"))
      .then((r) => r.json())
      .then((data) => setHistory(data))
      .catch(() => setHistory([]))
      .finally(() => setHistoryLoading(false));
  }, [activeTab]);

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

  const runScraper = () => {
    if (esRef.current) {
      esRef.current.close();
    }
    setRunState("loading");
    setProgressStep(0);
    setJobId(null);
    setErrorMessage("");
    setTypeCounts({});

    const params = new URLSearchParams({ mode: filterMode, filename });
    if (filterMode === "specific") params.append("months", months);
    if (filterMode === "range") {
      params.append("start", startMonth);
      params.append("end", endMonth);
    }

    const es = new EventSource(apiUrl(`/api/changelog/stream?${params}`));
    esRef.current = es;

    es.addEventListener("step", (e) => {
      const data = JSON.parse(e.data);
      setProgressStep(data.step);
    });

    es.addEventListener("complete", (e) => {
      const data = JSON.parse(e.data);
      setJobId(data.jobId);
      setTotalRecords(data.totalRecords);
      setMatchedRecords(data.matchedRecords);
      setTypeCounts(data.typeCounts);
      setProgressStep(PROGRESS_STEPS.length - 1);
      setRunState("success");
      es.close();
      esRef.current = null;
    });

    es.addEventListener("scrape-empty", (e) => {
      const data = JSON.parse(e.data);
      setTotalRecords(data.totalRecords);
      setRunState("empty");
      es.close();
      esRef.current = null;
    });

    es.addEventListener("scrape-error", (e) => {
      const data = JSON.parse(e.data);
      setErrorMessage(data.message);
      setRunState("error");
      es.close();
      esRef.current = null;
    });

    es.onerror = () => {
      setErrorMessage("Could not connect to the backend. Make sure the server is running on port 8000.");
      setRunState("error");
      es.close();
      esRef.current = null;
    };
  };

  const handleDownload = () => {
    if (!jobId) return;
    const a = document.createElement("a");
    a.href = apiUrl(`/api/changelog/download/${jobId}`);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
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
        onClick={runScraper}
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
                {totalRecords} records found · {matchedRecords} match your filter
              </p>
              <div className="flex flex-wrap gap-2 mt-2">
                {Object.entries(typeCounts).map(([type, count]) => (
                  <Badge key={type} variant="secondary">{type}: {count}</Badge>
                ))}
              </div>
            </div>
            <Button variant="outline" size="sm" onClick={handleDownload}>
              <Download className="w-4 h-4 mr-1.5" />
              {filename || "Download"}
            </Button>
          </div>
        </Card>
      )}

      {/* Empty — filter matched 0 records */}
      {runState === "empty" && (
        <Card className="p-6 border-amber-500/30 bg-amber-500/5 animate-slide-up">
          <div className="flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 text-amber-500 mt-0.5 shrink-0" />
            <div>
              <h3 className="font-semibold">No Records Matched</h3>
              <p className="text-sm text-muted-foreground mt-1">
                No records match your selected filter.
                {totalRecords > 0 && ` ${totalRecords} total records were found on the page.`}
                {" "}Try a different date range.
              </p>
            </div>
          </div>
        </Card>
      )}

      {/* Error */}
      {runState === "error" && (
        <Card className="p-6 border-destructive/30 bg-destructive/5 animate-slide-up">
          <div className="flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 text-destructive mt-0.5 shrink-0" />
            <div>
              <h3 className="font-semibold text-destructive">Scrape Failed</h3>
              <p className="text-sm text-muted-foreground mt-1">{errorMessage}</p>
            </div>
          </div>
        </Card>
      )}
      </>)}

      {/* History Tab */}
      {activeTab === "history" && (
        <Card className="animate-slide-up overflow-hidden">
          <div className="p-6 border-b">
            <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
              Past Exports
            </h3>
            <p className="text-xs text-muted-foreground mt-1">Previously generated changelog files</p>
          </div>
          {historyLoading ? (
            <div className="flex items-center justify-center gap-2 p-8 text-sm text-muted-foreground">
              <Loader2 className="w-4 h-4 animate-spin" />
              Loading history…
            </div>
          ) : history.length === 0 ? (
            <div className="p-8 text-center text-sm text-muted-foreground">
              No exports yet. Run the scraper to generate your first file.
            </div>
          ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Date</TableHead>
                  <TableHead>Filter</TableHead>
                  <TableHead className="text-right">Records</TableHead>
                  <TableHead className="text-right">Matched</TableHead>
                  <TableHead className="text-right">Size</TableHead>
                  <TableHead></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {history.map((run, i) => (
                  <TableRow key={`${run.date}-${i}`}>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <CalendarDays className="w-4 h-4 text-muted-foreground" />
                        <span className="font-medium">{run.date}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary" className="text-xs">{run.filter}</Badge>
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm">{run.totalRecords}</TableCell>
                    <TableCell className="text-right font-mono text-sm">{run.matchedRecords}</TableCell>
                    <TableCell className="text-right text-sm text-muted-foreground">{run.fileSize}</TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-8 w-8 p-0"
                        onClick={() => {
                          const a = document.createElement("a");
                          a.href = apiUrl(`/api/changelog/history/${encodeURIComponent(run.filename)}/download`);
                          a.download = run.filename;
                          document.body.appendChild(a);
                          a.click();
                          document.body.removeChild(a);
                        }}
                      >
                        <Download className="w-4 h-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          )}
        </Card>
      )}
    </div>
  );
};

export default ChangelogScraperPage;
