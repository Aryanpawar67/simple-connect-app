import { useState, useEffect, useRef } from "react";
import {
  Play,
  Zap,
  Layers,
  SlidersHorizontal,
  CheckCircle2,
  XCircle,
  Loader2,
  Download,
  ChevronDown,
  ChevronUp,
  Clock,
  History,
  FileText,
  CalendarDays,
  AlertCircle,
  Info,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

type ScrapeMode = "full" | "quick";
type RunState = "idle" | "scraping" | "processing" | "writing" | "success" | "error";
type ActiveTab = "run" | "history";
type SourceStatus = "pending" | "running" | "done" | "error";

interface SkillResult {
  skill_name: string;
  category: string;
  confidence_score: number;
  popularity: number;
  is_new: boolean;
  source: string;
}

interface ScrapeSummary {
  rawCount: number;
  dedupCount: number;
  finalCount: number;
  newCount: number;
  returningCount: number;
}

interface HistoryEntry {
  date: string;
  rows: number;
  newSkills: number;
  fileSize: string;
  formats: string[];
}

const ALL_SOURCES = [
  "GitHub Trending", "StackOverflow", "Hacker News", "npm Trending",
  "PyPI", "Product Hunt", "Dev.to", "Reddit",
  "arXiv", "ThoughtWorks Radar", "CNCF Landscape", "LinkedIn Jobs",
  "InfoQ", "DZone", "Medium", "GitHub Topics",
];

const QUICK_SOURCES = ["GitHub Trending", "StackOverflow", "CNCF Landscape", "Dev.to", "PyPI"];

const SOURCE_DESCRIPTIONS: Record<string, { what: string; why: string }> = {
  "GitHub Trending": {
    what: "Daily trending repositories across curated topics (AI, DevOps, ML, Kubernetes, Rust…).",
    why: "Surfaces tools and frameworks gaining rapid developer adoption — often the first place a new skill appears before reaching job postings.",
  },
  "StackOverflow": {
    what: "The most-asked-about programming tags on Stack Overflow, ranked by weekly activity.",
    why: "High-traffic tags directly reflect skills that working developers are actively using and struggling with — a strong signal of real-world demand.",
  },
  "Hacker News": {
    what: "Front-page stories and discussions from Hacker News (tech community aggregator).",
    why: "HN discussions reveal emerging tools and ideas weeks before they hit mainstream. Great for catching early-stage skills.",
  },
  "npm Trending": {
    what: "JavaScript/TypeScript packages with surging download counts across key keywords.",
    why: "Download trends are a direct signal of what frontend and fullstack developers are actively building with right now.",
  },
  "PyPI": {
    what: "Top downloaded Python packages from the Python Package Index.",
    why: "Covers AI/ML, data science, automation, and backend skills. High download volume = active practitioner adoption.",
  },
  "Product Hunt": {
    what: "Newly launched developer tools, platforms, and APIs featured on Product Hunt.",
    why: "Early indicator of tools that may become standard skills within 1–2 years. Good for spotting emerging SaaS and developer tooling trends.",
  },
  "Dev.to": {
    what: "Developer blog articles ranked by engagement, filtered by tech topic tags.",
    why: "High-engagement posts signal skills people are actively learning and teaching. Reflects grassroots adoption before enterprise uptake.",
  },
  "Reddit": {
    what: "Hot posts from programming and tech subreddits (r/programming, r/MachineLearning, r/devops, r/kubernetes, etc.).",
    why: "Community-level conversations surface practitioner skills and strong opinions about what tools actually work in production.",
  },
  "arXiv": {
    what: "Academic pre-prints from CS, ML, distributed systems, and security research feeds.",
    why: "Leading indicator — research techniques here typically become production skills within 2–3 years. Essential for tracking AI/ML skill trajectories.",
  },
  "ThoughtWorks Radar": {
    what: "ThoughtWorks' quarterly Technology Radar — categorises tech as Adopt, Trial, Assess, or Hold.",
    why: "One of the most authoritative practitioner signals for enterprise tech skills. Widely used by CTOs and tech leads for roadmap decisions.",
  },
  "CNCF Landscape": {
    what: "All projects in the Cloud Native Computing Foundation landscape (Kubernetes ecosystem, service mesh, observability, storage, etc.).",
    why: "Covers the full cloud-native stack end-to-end. If a tool is in the CNCF landscape it's relevant to platform and DevOps engineers.",
  },
  "LinkedIn Jobs": {
    what: "Active job postings for tech roles (AI engineer, MLOps, platform engineer, DevSecOps, cloud architect, data engineer).",
    why: "The most direct signal of employer-demanded skills right now. What appears in job descriptions today becomes a required skill in 6–12 months.",
  },
  "InfoQ": {
    what: "Enterprise software development news and articles covering architecture, platforms, and methodologies.",
    why: "Targets senior engineers and architects. Skills discussed on InfoQ tend to be production-ready and adopted at scale.",
  },
  "DZone": {
    what: "Developer-focused tutorials and articles across frameworks, tools, and best practices.",
    why: "Broad coverage of all tech domains. Popular DZone content reflects what mid-level engineers are learning and applying day-to-day.",
  },
  "Medium": {
    what: "Technical blog posts by engineers, filtered across programming, ML, DevOps, security, and cloud tags.",
    why: "Popular posts reveal skills developers are investing time in writing and reading about — a soft signal of momentum and community interest.",
  },
  "GitHub Topics": {
    what: "GitHub's curated topic taxonomy — top repositories grouped by technology category.",
    why: "Clean, structured signal for technology categories gaining significant open-source activity. Useful for discovering subcategories and tool clusters.",
  },
};

const SkillScraperPage = () => {
  const [activeTab, setActiveTab] = useState<ActiveTab>("run");
  const [mode, setMode] = useState<ScrapeMode>("quick");
  const [selectedSources, setSelectedSources] = useState<string[]>(QUICK_SOURCES);
  const [threshold, setThreshold] = useState(0.25);
  const [outputFormats, setOutputFormats] = useState({ csv: true, excel: true });
  const [showSources, setShowSources] = useState(false);
  const [runState, setRunState] = useState<RunState>("idle");
  const [sourceProgress, setSourceProgress] = useState<Record<string, SourceStatus>>({});
  const [sourceCounts, setSourceCounts] = useState<Record<string, number>>({});
  const [sourceErrors, setSourceErrors] = useState<Record<string, string>>({});
  const [results, setResults] = useState<SkillResult[]>([]);
  const [summary, setSummary] = useState<ScrapeSummary | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  const handleModeChange = (newMode: ScrapeMode) => {
    setMode(newMode);
    setSelectedSources(newMode === "quick" ? QUICK_SOURCES : [...ALL_SOURCES]);
  };

  const toggleSource = (source: string) => {
    setSelectedSources((prev) =>
      prev.includes(source) ? prev.filter((s) => s !== source) : [...prev, source]
    );
  };

  const loadHistory = async () => {
    setHistoryLoading(true);
    try {
      const res = await fetch("/api/skills/history");
      if (res.ok) {
        setHistory(await res.json());
      }
    } catch {
      // silently fail — history stays empty
    } finally {
      setHistoryLoading(false);
    }
  };

  useEffect(() => {
    if (activeTab === "history") {
      loadHistory();
    }
  }, [activeTab]);

  // Cleanup EventSource on unmount
  useEffect(() => {
    return () => { esRef.current?.close(); };
  }, []);

  const startRun = () => {
    if (esRef.current) {
      esRef.current.close();
    }

    // Reset state
    setRunState("scraping");
    setResults([]);
    setSummary(null);
    setJobId(null);
    setErrorMessage(null);
    setSourceCounts({});
    setSourceErrors({});

    const initial: Record<string, SourceStatus> = {};
    selectedSources.forEach((s) => (initial[s] = "pending"));
    setSourceProgress({ ...initial });

    const formats: string[] = [];
    if (outputFormats.csv) formats.push("csv");
    if (outputFormats.excel) formats.push("xlsx");

    const params = new URLSearchParams({
      sources: selectedSources.join(","),
      threshold: String(threshold),
      formats: formats.join(",") || "csv",
    });

    const es = new EventSource(`/api/skills/stream?${params}`);
    esRef.current = es;

    es.addEventListener("source-start", (e) => {
      const { source } = JSON.parse(e.data);
      setSourceProgress((prev) => ({ ...prev, [source]: "running" }));
    });

    es.addEventListener("source-done", (e) => {
      const { source, count } = JSON.parse(e.data);
      setSourceProgress((prev) => ({ ...prev, [source]: "done" }));
      setSourceCounts((prev) => ({ ...prev, [source]: count }));
    });

    es.addEventListener("source-error", (e) => {
      const { source, error } = JSON.parse(e.data);
      setSourceProgress((prev) => ({ ...prev, [source]: "error" }));
      setSourceErrors((prev) => ({ ...prev, [source]: error || "Failed" }));
    });

    es.addEventListener("processing", () => {
      setRunState("processing");
    });

    es.addEventListener("writing", () => {
      setRunState("writing");
    });

    es.addEventListener("complete", (e) => {
      const data = JSON.parse(e.data);
      setRunState("success");
      setJobId(data.jobId);
      setResults(data.results ?? []);
      setSummary({
        rawCount: data.rawCount,
        dedupCount: data.dedupCount,
        finalCount: data.finalCount,
        newCount: data.newCount,
        returningCount: data.returningCount,
      });
      es.close();
    });

    es.addEventListener("skill-error", (e) => {
      const { message } = JSON.parse(e.data);
      setRunState("error");
      setErrorMessage(message);
      es.close();
    });

    es.onerror = () => {
      if (runState !== "success" && runState !== "error") {
        setRunState("error");
        setErrorMessage("Connection to server lost. Is the backend running?");
      }
      es.close();
    };
  };

  const downloadFile = (format: "csv" | "xlsx") => {
    if (!jobId) return;
    const a = document.createElement("a");
    a.href = `/api/skills/download/${jobId}?format=${format}`;
    a.click();
  };

  const downloadHistory = (date: string, format: string) => {
    const a = document.createElement("a");
    a.href = `/api/skills/history/${date}/download?format=${format.toLowerCase()}`;
    a.click();
  };

  const isRunning = runState === "scraping" || runState === "processing" || runState === "writing";

  return (
    <div className="max-w-4xl mx-auto space-y-6 animate-fade-in">
      {/* Tab Switcher */}
      <div className="flex gap-1 bg-secondary rounded-xl p-1">
        {[
          { id: "run" as ActiveTab, label: "Run Scrape", icon: Play },
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
      {/* Mode Selection */}
      <Card className="p-6">
        <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-4">
          Scrape Mode
        </h3>
        <div className="flex gap-3">
          {[
            { id: "quick" as const, label: "Quick", desc: "Top 5 sources", icon: Zap },
            { id: "full" as const, label: "Full", desc: "All 16 sources", icon: Layers },
          ].map((opt) => {
            const Icon = opt.icon;
            return (
              <button
                key={opt.id}
                onClick={() => handleModeChange(opt.id)}
                disabled={isRunning}
                className={cn(
                  "flex-1 flex items-center gap-3 p-4 rounded-xl border-2 transition-all",
                  mode === opt.id
                    ? "border-primary bg-primary/5"
                    : "border-border hover:border-muted-foreground/30",
                  isRunning && "opacity-50 cursor-not-allowed"
                )}
              >
                <Icon className={cn("w-5 h-5", mode === opt.id ? "text-primary" : "text-muted-foreground")} />
                <div className="text-left">
                  <div className="text-sm font-medium">{opt.label}</div>
                  <div className="text-xs text-muted-foreground">{opt.desc}</div>
                </div>
              </button>
            );
          })}
        </div>
      </Card>

      {/* Source Selection (collapsible) */}
      <Card className="overflow-hidden">
        <button
          onClick={() => setShowSources(!showSources)}
          className="w-full flex items-center justify-between p-6 hover:bg-secondary/50 transition-colors"
        >
          <div className="flex items-center gap-2">
            <SlidersHorizontal className="w-4 h-4 text-muted-foreground" />
            <span className="text-sm font-medium">Sources</span>
            <Badge variant="secondary" className="ml-2">
              {selectedSources.length} / {ALL_SOURCES.length}
            </Badge>
          </div>
          {showSources ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>
        {showSources && (
          <div className="px-6 pb-6 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2 animate-slide-up">
            <TooltipProvider delayDuration={200}>
              {ALL_SOURCES.map((source) => {
                const desc = SOURCE_DESCRIPTIONS[source];
                return (
                  <Tooltip key={source}>
                    <TooltipTrigger asChild>
                      <label
                        className={cn(
                          "flex items-center gap-2 px-3 py-2 rounded-lg border text-sm cursor-pointer transition-colors",
                          selectedSources.includes(source)
                            ? "border-primary/40 bg-primary/5"
                            : "border-border hover:bg-secondary",
                          isRunning && "opacity-50 pointer-events-none"
                        )}
                      >
                        <input
                          type="checkbox"
                          checked={selectedSources.includes(source)}
                          onChange={() => toggleSource(source)}
                          disabled={isRunning}
                          className="accent-[hsl(var(--primary))] rounded"
                        />
                        <span className="truncate flex-1">{source}</span>
                        <Info className="w-3 h-3 text-muted-foreground/50 shrink-0" />
                      </label>
                    </TooltipTrigger>
                    {desc && (
                      <TooltipContent side="top" className="max-w-xs p-3 space-y-1.5">
                        <p className="font-medium text-xs">{source}</p>
                        <p className="text-xs text-muted-foreground leading-relaxed">{desc.what}</p>
                        <p className="text-xs leading-relaxed border-t pt-1.5">
                          <span className="font-medium">Why it helps: </span>
                          {desc.why}
                        </p>
                      </TooltipContent>
                    )}
                  </Tooltip>
                );
              })}
            </TooltipProvider>
          </div>
        )}
      </Card>

      {/* Settings row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Card className="p-6">
          <label className="text-sm font-medium text-muted-foreground block mb-3">
            Confidence Threshold: <span className="text-foreground font-semibold">{threshold.toFixed(2)}</span>
          </label>
          <Slider
            value={[threshold]}
            onValueChange={([v]) => setThreshold(v)}
            min={0}
            max={1}
            step={0.05}
            disabled={isRunning}
          />
          <p className="text-xs text-muted-foreground mt-2">
            Skills scoring below this are excluded from results
          </p>
        </Card>

        <Card className="p-6">
          <label className="text-sm font-medium text-muted-foreground block mb-3">
            Output Format
          </label>
          <div className="flex gap-3">
            {(["csv", "excel"] as const).map((fmt) => (
              <label
                key={fmt}
                className={cn(
                  "flex items-center gap-2 px-4 py-2 rounded-lg border text-sm cursor-pointer transition-colors",
                  outputFormats[fmt]
                    ? "border-primary/40 bg-primary/5"
                    : "border-border hover:bg-secondary",
                  isRunning && "opacity-50 pointer-events-none"
                )}
              >
                <input
                  type="checkbox"
                  checked={outputFormats[fmt]}
                  onChange={() =>
                    setOutputFormats((prev) => ({ ...prev, [fmt]: !prev[fmt] }))
                  }
                  disabled={isRunning}
                  className="accent-[hsl(var(--primary))]"
                />
                {fmt === "csv" ? "CSV" : "Excel"}
              </label>
            ))}
          </div>
        </Card>
      </div>

      {/* Run Button */}
      <Button
        size="lg"
        onClick={startRun}
        disabled={isRunning || selectedSources.length === 0 || (!outputFormats.csv && !outputFormats.excel)}
        className="w-full h-12 text-base font-semibold"
      >
        {isRunning ? (
          <>
            <Loader2 className="w-5 h-5 mr-2 animate-spin" />
            {runState === "scraping" ? "Scraping sources…" : runState === "processing" ? "Processing…" : "Saving files…"}
          </>
        ) : (
          <>
            <Play className="w-5 h-5 mr-2" />
            Start Scrape
          </>
        )}
      </Button>

      {/* Progress Feed */}
      {runState !== "idle" && Object.keys(sourceProgress).length > 0 && (
        <Card className="p-6 animate-slide-up">
          <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-3">
            Progress
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {Object.entries(sourceProgress).map(([source, status]) => (
              <div
                key={source}
                className="flex items-center gap-2 px-3 py-2 rounded-lg bg-secondary/50 text-sm"
              >
                {status === "pending" && <Clock className="w-4 h-4 text-muted-foreground" />}
                {status === "running" && <Loader2 className="w-4 h-4 text-primary animate-spin" />}
                {status === "done" && <CheckCircle2 className="w-4 h-4 text-success" />}
                {status === "error" && <XCircle className="w-4 h-4 text-destructive" />}
                <span className={cn(status === "error" && "text-destructive")}>{source}</span>
                {status === "done" && sourceCounts[source] !== undefined && (
                  <span className="ml-auto text-xs text-muted-foreground">
                    {sourceCounts[source]} items
                  </span>
                )}
                {status === "error" && (
                  <span className="ml-auto text-xs text-destructive truncate max-w-[100px]" title={sourceErrors[source]}>
                    {sourceErrors[source] ?? "Error"}
                  </span>
                )}
              </div>
            ))}
          </div>
          {(runState === "processing" || runState === "writing") && (
            <p className="text-xs text-muted-foreground mt-3 flex items-center gap-1.5">
              <Loader2 className="w-3 h-3 animate-spin" />
              {runState === "processing" ? "Classifying / Deduplicating / Scoring…" : "Saving files…"}
            </p>
          )}
        </Card>
      )}

      {/* Error Banner */}
      {runState === "error" && errorMessage && (
        <Card className="p-6 border-destructive/30 bg-destructive/5 animate-slide-up">
          <h3 className="font-semibold flex items-center gap-2 text-destructive">
            <AlertCircle className="w-5 h-5" />
            Scrape Failed
          </h3>
          <p className="text-sm text-muted-foreground mt-1">{errorMessage}</p>
        </Card>
      )}

      {/* Success Summary */}
      {runState === "success" && summary && (
        <Card className="p-6 border-success/30 bg-success/5 animate-slide-up">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h3 className="font-semibold flex items-center gap-2">
                <CheckCircle2 className="w-5 h-5 text-success" />
                Scrape Complete
              </h3>
              <p className="text-sm text-muted-foreground mt-1">
                {summary.rawCount} raw signals → {summary.dedupCount} after dedup → {summary.finalCount} after confidence filter
                {" · "}<span className="font-medium text-foreground">{summary.newCount} new</span>
                {" · "}{summary.returningCount} returning
              </p>
            </div>
            <div className="flex gap-2 shrink-0">
              {outputFormats.csv && (
                <Button variant="outline" size="sm" onClick={() => downloadFile("csv")}>
                  <Download className="w-4 h-4 mr-1.5" />
                  CSV
                </Button>
              )}
              {outputFormats.excel && (
                <Button variant="outline" size="sm" onClick={() => downloadFile("xlsx")}>
                  <Download className="w-4 h-4 mr-1.5" />
                  Excel
                </Button>
              )}
            </div>
          </div>
        </Card>
      )}

      {/* Results Table */}
      {results.length > 0 && (
        <Card className="animate-slide-up overflow-hidden">
          <div className="p-6 border-b">
            <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
              Top Results
            </h3>
          </div>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Skill</TableHead>
                  <TableHead>Category</TableHead>
                  <TableHead className="text-right">Confidence</TableHead>
                  <TableHead className="text-right">Popularity</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {results.map((row) => (
                  <TableRow key={row.skill_name}>
                    <TableCell className="font-medium">{row.skill_name}</TableCell>
                    <TableCell className="text-muted-foreground">{row.category}</TableCell>
                    <TableCell className="text-right">
                      <span className={cn(
                        "font-mono text-sm",
                        row.confidence_score >= 0.8 ? "text-success" : "text-muted-foreground"
                      )}>
                        {row.confidence_score.toFixed(2)}
                      </span>
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm">{row.popularity}</TableCell>
                    <TableCell className="text-muted-foreground text-sm">{row.source}</TableCell>
                    <TableCell>
                      <Badge variant={row.is_new ? "default" : "secondary"} className="text-xs">
                        {row.is_new ? "New" : "Returning"}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </Card>
      )}
      </>)}

      {/* History Tab */}
      {activeTab === "history" && (
        <Card className="animate-slide-up overflow-hidden">
          <div className="p-6 border-b">
            <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
              Past Scrape Runs
            </h3>
            <p className="text-xs text-muted-foreground mt-1">Download a sheet by clicking its format badge</p>
          </div>

          {historyLoading ? (
            <div className="p-12 text-center">
              <Loader2 className="w-6 h-6 text-muted-foreground/40 mx-auto mb-3 animate-spin" />
              <p className="text-sm text-muted-foreground">Loading history…</p>
            </div>
          ) : history.length === 0 ? (
            <div className="p-12 text-center">
              <FileText className="w-10 h-10 text-muted-foreground/40 mx-auto mb-3" />
              <p className="text-sm text-muted-foreground">No scrapes run yet — start your first scrape</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Date</TableHead>
                    <TableHead className="text-right">Skills Found</TableHead>
                    <TableHead className="text-right">New</TableHead>
                    <TableHead className="text-right">File Size</TableHead>
                    <TableHead>Download</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {history.map((run) => (
                    <TableRow key={run.date}>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <CalendarDays className="w-4 h-4 text-muted-foreground" />
                          <span className="font-medium">{run.date}</span>
                        </div>
                      </TableCell>
                      <TableCell className="text-right font-mono text-sm">{run.rows}</TableCell>
                      <TableCell className="text-right">
                        <Badge variant="default" className="text-xs">{run.newSkills} new</Badge>
                      </TableCell>
                      <TableCell className="text-right text-sm text-muted-foreground">{run.fileSize}</TableCell>
                      <TableCell>
                        <div className="flex gap-1">
                          {run.formats.map((f) => (
                            <button
                              key={f}
                              onClick={() => downloadHistory(run.date, f)}
                              className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-secondary hover:bg-secondary/80 transition-colors"
                            >
                              <Download className="w-3 h-3" />
                              {f}
                            </button>
                          ))}
                        </div>
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

export default SkillScraperPage;
