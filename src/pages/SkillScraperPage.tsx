import { useState } from "react";
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

type ScrapeMode = "full" | "quick";
type RunState = "idle" | "scraping" | "processing" | "writing" | "success" | "error";

const ALL_SOURCES = [
  "GitHub Trending", "StackOverflow", "Hacker News", "npm Trending",
  "PyPI", "Product Hunt", "Dev.to", "Reddit",
  "arXiv", "ThoughtWorks Radar", "CNCF Landscape", "LinkedIn Jobs",
  "InfoQ", "DZone", "Medium", "GitHub Topics",
];

const QUICK_SOURCES = ["GitHub Trending", "StackOverflow", "CNCF Landscape", "Dev.to", "PyPI"];

const MOCK_RESULTS = [
  { skill_name: "Rust", category: "Programming Language", confidence_score: 0.95, popularity: 892, is_new: false, source: "GitHub Trending" },
  { skill_name: "LangChain", category: "AI/ML Framework", confidence_score: 0.91, popularity: 756, is_new: true, source: "Dev.to" },
  { skill_name: "Bun", category: "Runtime", confidence_score: 0.88, popularity: 621, is_new: false, source: "npm Trending" },
  { skill_name: "Ollama", category: "AI/ML Tool", confidence_score: 0.86, popularity: 589, is_new: true, source: "GitHub Trending" },
  { skill_name: "Deno 2", category: "Runtime", confidence_score: 0.82, popularity: 445, is_new: true, source: "Hacker News" },
  { skill_name: "HTMX", category: "Web Framework", confidence_score: 0.79, popularity: 412, is_new: false, source: "Reddit" },
  { skill_name: "Zig", category: "Programming Language", confidence_score: 0.76, popularity: 389, is_new: true, source: "GitHub Topics" },
  { skill_name: "Mojo", category: "Programming Language", confidence_score: 0.73, popularity: 356, is_new: true, source: "arXiv" },
];

const SkillScraperPage = () => {
  const [mode, setMode] = useState<ScrapeMode>("quick");
  const [selectedSources, setSelectedSources] = useState<string[]>(QUICK_SOURCES);
  const [threshold, setThreshold] = useState(0.25);
  const [outputFormats, setOutputFormats] = useState({ csv: true, excel: true });
  const [showSources, setShowSources] = useState(false);
  const [runState, setRunState] = useState<RunState>("idle");
  const [sourceProgress, setSourceProgress] = useState<Record<string, "pending" | "running" | "done" | "error">>({});
  const [showResults, setShowResults] = useState(false);

  const handleModeChange = (newMode: ScrapeMode) => {
    setMode(newMode);
    setSelectedSources(newMode === "quick" ? QUICK_SOURCES : [...ALL_SOURCES]);
  };

  const toggleSource = (source: string) => {
    setSelectedSources((prev) =>
      prev.includes(source) ? prev.filter((s) => s !== source) : [...prev, source]
    );
  };

  const simulateRun = async () => {
    setRunState("scraping");
    setShowResults(false);

    const progress: Record<string, "pending" | "running" | "done" | "error"> = {};
    selectedSources.forEach((s) => (progress[s] = "pending"));
    setSourceProgress({ ...progress });

    for (const source of selectedSources) {
      progress[source] = "running";
      setSourceProgress({ ...progress });
      await new Promise((r) => setTimeout(r, 400 + Math.random() * 600));
      progress[source] = source === "LinkedIn Jobs" ? "error" : "done";
      setSourceProgress({ ...progress });
    }

    setRunState("processing");
    await new Promise((r) => setTimeout(r, 1200));

    setRunState("writing");
    await new Promise((r) => setTimeout(r, 600));

    setRunState("success");
    setShowResults(true);
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6 animate-fade-in">
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
                className={cn(
                  "flex-1 flex items-center gap-3 p-4 rounded-xl border-2 transition-all",
                  mode === opt.id
                    ? "border-primary bg-primary/5"
                    : "border-border hover:border-muted-foreground/30"
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
            {ALL_SOURCES.map((source) => (
              <label
                key={source}
                className={cn(
                  "flex items-center gap-2 px-3 py-2 rounded-lg border text-sm cursor-pointer transition-colors",
                  selectedSources.includes(source)
                    ? "border-primary/40 bg-primary/5"
                    : "border-border hover:bg-secondary"
                )}
              >
                <input
                  type="checkbox"
                  checked={selectedSources.includes(source)}
                  onChange={() => toggleSource(source)}
                  className="accent-[hsl(var(--primary))] rounded"
                />
                <span className="truncate">{source}</span>
              </label>
            ))}
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
                    : "border-border hover:bg-secondary"
                )}
              >
                <input
                  type="checkbox"
                  checked={outputFormats[fmt]}
                  onChange={() =>
                    setOutputFormats((prev) => ({ ...prev, [fmt]: !prev[fmt] }))
                  }
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
        onClick={simulateRun}
        disabled={runState === "scraping" || runState === "processing" || runState === "writing" || selectedSources.length === 0}
        className="w-full h-12 text-base font-semibold"
      >
        {runState === "scraping" || runState === "processing" || runState === "writing" ? (
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
                {status === "done" && (
                  <span className="ml-auto text-xs text-muted-foreground">
                    {Math.floor(Math.random() * 80 + 10)} items
                  </span>
                )}
                {status === "error" && (
                  <span className="ml-auto text-xs text-destructive">403</span>
                )}
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Success Summary */}
      {runState === "success" && (
        <Card className="p-6 border-success/30 bg-success/5 animate-slide-up">
          <div className="flex items-start justify-between">
            <div>
              <h3 className="font-semibold flex items-center gap-2">
                <CheckCircle2 className="w-5 h-5 text-success" />
                Scrape Complete
              </h3>
              <p className="text-sm text-muted-foreground mt-1">
                247 raw signals → 182 after dedup → 156 after confidence filter · <span className="font-medium text-foreground">38 new</span> · 118 returning
              </p>
            </div>
            <Button variant="outline" size="sm">
              <Download className="w-4 h-4 mr-1.5" />
              Download
            </Button>
          </div>
        </Card>
      )}

      {/* Results Table */}
      {showResults && (
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
                {MOCK_RESULTS.map((row) => (
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
    </div>
  );
};

export default SkillScraperPage;
