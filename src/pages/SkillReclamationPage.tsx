import { useState, useEffect, useCallback } from "react";
import {
  Recycle,
  Loader2,
  RefreshCw,
  CheckCircle2,
  XCircle,
  Sparkles,
  ArrowUpCircle,
  Ban,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
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
import { Checkbox } from "@/components/ui/checkbox";

interface ReclaimItem {
  id: number;
  skill_name: string;
  category: string;
  subcategory: string;
  source: string;
  confidence_score: number;
  popularity: number;
  times_rejected?: number;
  run_count?: number;
  first_rejected_at?: string;
  first_seen?: string;
  pool: "rejected" | "unmerged";
}

interface AiVerdict {
  verdict: "keep" | "skip";
  reason: string;
}

type PoolFilter = "all" | "rejected" | "unmerged";

function confidenceColor(score: number): string {
  if (score >= 0.7) return "text-green-600 font-semibold";
  if (score >= 0.4) return "text-amber-600 font-semibold";
  return "text-red-500 font-semibold";
}

function PoolBadge({ pool }: { pool: "rejected" | "unmerged" }) {
  return pool === "rejected" ? (
    <Badge variant="destructive" className="text-xs">Below Threshold</Badge>
  ) : (
    <Badge variant="secondary" className="text-xs">Never Merged</Badge>
  );
}

const API = "/api";

export default function SkillReclamationPage() {
  const [poolData, setPoolData] = useState<{
    rejected: ReclaimItem[];
    unmerged: ReclaimItem[];
    rejected_count: number;
    unmerged_count: number;
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [pool, setPool] = useState<PoolFilter>("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [aiReviewing, setAiReviewing] = useState(false);
  const [aiResults, setAiResults] = useState<Map<string, AiVerdict>>(new Map());
  const [promoting, setPromoting] = useState(false);
  const [dismissing, setDismissing] = useState(false);
  const [actionResult, setActionResult] = useState<string | null>(null);

  const fetchPool = useCallback(async () => {
    setLoading(true);
    setActionResult(null);
    try {
      const res = await fetch(`${API}/skills/reclaim-pool?pool=all`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const rejected: ReclaimItem[] = (data.rejected || []).map((r: ReclaimItem) => ({
        ...r,
        pool: "rejected" as const,
      }));
      const unmerged: ReclaimItem[] = (data.unmerged || []).map((r: ReclaimItem) => ({
        ...r,
        pool: "unmerged" as const,
      }));
      setPoolData({ ...data, rejected, unmerged });
      setSelected(new Set());
      setAiResults(new Map());
    } catch (err) {
      setActionResult(`Failed to load reclaim pool: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPool();
  }, [fetchPool]);

  const visibleItems: ReclaimItem[] = poolData
    ? [
        ...(pool !== "unmerged" ? poolData.rejected : []),
        ...(pool !== "rejected" ? poolData.unmerged : []),
      ]
    : [];

  function toggleItem(key: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function toggleAll() {
    if (selected.size === visibleItems.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(visibleItems.map((i) => `${i.pool}:${i.id}`)));
    }
  }

  function selectedByPool(p: "rejected" | "unmerged"): number[] {
    const ids: number[] = [];
    for (const key of selected) {
      const [kpool, kid] = key.split(":");
      if (kpool === p) ids.push(Number(kid));
    }
    return ids;
  }

  async function runAiReview() {
    const items = visibleItems.filter((i) => selected.has(`${i.pool}:${i.id}`));
    if (!items.length) return;
    setAiReviewing(true);
    setActionResult(null);
    try {
      const res = await fetch(`${API}/skills/reclaim-pool/ai-review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ skills: items }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const map = new Map<string, AiVerdict>();
      for (const rec of data.recommendations || []) {
        map.set(rec.skill_name, { verdict: rec.verdict, reason: rec.reason });
      }
      setAiResults(map);
    } catch (err) {
      setActionResult(`AI review failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setAiReviewing(false);
    }
  }

  async function promote() {
    const rejectedIds = selectedByPool("rejected");
    const unmergedIds = selectedByPool("unmerged");
    if (!rejectedIds.length && !unmergedIds.length) return;
    setPromoting(true);
    setActionResult(null);
    try {
      let total = 0;
      if (rejectedIds.length) {
        const res = await fetch(`${API}/skills/reclaim-pool/promote`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ids: rejectedIds, pool: "rejected" }),
        });
        const data = await res.json();
        total += data.promoted || 0;
      }
      if (unmergedIds.length) {
        const res = await fetch(`${API}/skills/reclaim-pool/promote`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ids: unmergedIds, pool: "unmerged" }),
        });
        const data = await res.json();
        total += data.promoted || 0;
      }
      setActionResult(`Promoted ${total} skill${total !== 1 ? "s" : ""} into the active pool.`);
      fetchPool();
    } catch (err) {
      setActionResult(`Promote failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setPromoting(false);
    }
  }

  async function dismiss() {
    const rejectedIds = selectedByPool("rejected");
    const unmergedIds = selectedByPool("unmerged");
    if (!rejectedIds.length && !unmergedIds.length) return;
    setDismissing(true);
    setActionResult(null);
    try {
      let total = 0;
      if (rejectedIds.length) {
        const res = await fetch(`${API}/skills/reclaim-pool/dismiss`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ids: rejectedIds, pool: "rejected" }),
        });
        const data = await res.json();
        total += data.dismissed || 0;
      }
      if (unmergedIds.length) {
        const res = await fetch(`${API}/skills/reclaim-pool/dismiss`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ids: unmergedIds, pool: "unmerged" }),
        });
        const data = await res.json();
        total += data.dismissed || 0;
      }
      setActionResult(`Dismissed ${total} skill${total !== 1 ? "s" : ""}.`);
      fetchPool();
    } catch (err) {
      setActionResult(`Dismiss failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setDismissing(false);
    }
  }

  const keepItems = [...aiResults.entries()].filter(([, v]) => v.verdict === "keep");
  const skipItems = [...aiResults.entries()].filter(([, v]) => v.verdict === "skip");
  const hasAiResults = aiResults.size > 0;

  return (
    <div className="space-y-6 max-w-6xl">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Recycle className="w-5 h-5 text-primary" />
            <h1 className="text-xl font-bold">Skill Reclamation</h1>
          </div>
          <p className="text-sm text-muted-foreground max-w-2xl">
            Skills end up here in two ways: <strong>Below Threshold</strong> — rejected during
            scraping because confidence was too low, and <strong>Never Merged</strong> — saved to
            the DB but not yet added to the master taxonomy. Use AI review to find hidden gems worth
            promoting.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={fetchPool} disabled={loading}>
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
          <span className="ml-1.5">Refresh</span>
        </Button>
      </div>

      {/* Summary stats */}
      {poolData && (
        <div className="flex gap-3 flex-wrap">
          <Card className="px-4 py-3 flex items-center gap-3">
            <XCircle className="w-4 h-4 text-destructive" />
            <div>
              <div className="text-xs text-muted-foreground">Below Threshold</div>
              <div className="text-lg font-bold">{poolData.rejected_count}</div>
            </div>
          </Card>
          <Card className="px-4 py-3 flex items-center gap-3">
            <CheckCircle2 className="w-4 h-4 text-amber-500" />
            <div>
              <div className="text-xs text-muted-foreground">Never Merged</div>
              <div className="text-lg font-bold">{poolData.unmerged_count}</div>
            </div>
          </Card>
          <Card className="px-4 py-3 flex items-center gap-3">
            <Sparkles className="w-4 h-4 text-blue-500" />
            <div>
              <div className="text-xs text-muted-foreground">Total in Pool</div>
              <div className="text-lg font-bold">{poolData.rejected_count + poolData.unmerged_count}</div>
            </div>
          </Card>
        </div>
      )}

      {/* Filter tabs */}
      <div className="flex gap-1 border-b">
        {(["all", "rejected", "unmerged"] as PoolFilter[]).map((tab) => (
          <button
            key={tab}
            onClick={() => { setPool(tab); setSelected(new Set()); }}
            className={cn(
              "px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors",
              pool === tab
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            {tab === "all" ? "All" : tab === "rejected" ? "Below Threshold" : "Never Merged"}
          </button>
        ))}
      </div>

      {/* Action bar */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-sm text-muted-foreground">
          {selected.size} selected
        </span>
        <Button
          size="sm"
          variant="outline"
          onClick={runAiReview}
          disabled={selected.size === 0 || aiReviewing}
        >
          {aiReviewing ? (
            <Loader2 className="w-4 h-4 animate-spin mr-1.5" />
          ) : (
            <Sparkles className="w-4 h-4 mr-1.5" />
          )}
          Run AI Review ({selected.size} selected)
        </Button>
        <Button
          size="sm"
          variant="default"
          onClick={promote}
          disabled={selected.size === 0 || promoting}
        >
          {promoting ? (
            <Loader2 className="w-4 h-4 animate-spin mr-1.5" />
          ) : (
            <ArrowUpCircle className="w-4 h-4 mr-1.5" />
          )}
          Promote Selected
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={dismiss}
          disabled={selected.size === 0 || dismissing}
          className="text-muted-foreground hover:text-destructive"
        >
          {dismissing ? (
            <Loader2 className="w-4 h-4 animate-spin mr-1.5" />
          ) : (
            <Ban className="w-4 h-4 mr-1.5" />
          )}
          Dismiss Selected
        </Button>
      </div>

      {/* Action result message */}
      {actionResult && (
        <div className={cn(
          "text-sm px-4 py-2.5 rounded-md border",
          actionResult.toLowerCase().includes("fail") || actionResult.toLowerCase().includes("error")
            ? "bg-destructive/10 border-destructive/30 text-destructive"
            : "bg-green-50 border-green-200 text-green-800"
        )}>
          {actionResult}
        </div>
      )}

      {/* AI results panel */}
      {hasAiResults && (
        <Card className="p-4 space-y-4">
          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-blue-500" />
            <span className="font-semibold text-sm">AI Review Results</span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <div className="text-xs font-semibold text-green-700 mb-2">
                Recommended to Keep ({keepItems.length})
              </div>
              <div className="space-y-1.5">
                {keepItems.map(([name, v]) => (
                  <div key={name} className="flex items-start gap-2 bg-green-50 border border-green-200 rounded px-3 py-2">
                    <CheckCircle2 className="w-3.5 h-3.5 text-green-600 mt-0.5 shrink-0" />
                    <div>
                      <div className="text-xs font-medium text-green-900">{name}</div>
                      <div className="text-xs text-green-700">{v.reason}</div>
                    </div>
                  </div>
                ))}
                {keepItems.length === 0 && (
                  <div className="text-xs text-muted-foreground italic">None recommended.</div>
                )}
              </div>
            </div>
            <div>
              <div className="text-xs font-semibold text-muted-foreground mb-2">
                Skip ({skipItems.length})
              </div>
              <div className="space-y-1.5">
                {skipItems.map(([name, v]) => (
                  <div key={name} className="flex items-start gap-2 bg-secondary/50 rounded px-3 py-2">
                    <XCircle className="w-3.5 h-3.5 text-muted-foreground mt-0.5 shrink-0" />
                    <div>
                      <div className="text-xs font-medium">{name}</div>
                      <div className="text-xs text-muted-foreground">{v.reason}</div>
                    </div>
                  </div>
                ))}
                {skipItems.length === 0 && (
                  <div className="text-xs text-muted-foreground italic">None to skip.</div>
                )}
              </div>
            </div>
          </div>
        </Card>
      )}

      {/* Skills table */}
      {loading ? (
        <div className="flex items-center justify-center py-20 text-muted-foreground">
          <Loader2 className="w-6 h-6 animate-spin mr-2" />
          Loading reclaim pool…
        </div>
      ) : visibleItems.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-muted-foreground gap-2">
          <Recycle className="w-8 h-8 opacity-30" />
          <div className="text-sm">No skills in the reclaim pool.</div>
          <div className="text-xs">Skills rejected below confidence threshold will appear here.</div>
        </div>
      ) : (
        <Card className="overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">
                  <Checkbox
                    checked={selected.size === visibleItems.length && visibleItems.length > 0}
                    onCheckedChange={toggleAll}
                  />
                </TableHead>
                <TableHead>Skill</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Confidence</TableHead>
                <TableHead>Times Seen</TableHead>
                <TableHead>Category</TableHead>
                <TableHead>AI Verdict</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visibleItems.map((item) => {
                const key = `${item.pool}:${item.id}`;
                const verdict = aiResults.get(item.skill_name);
                return (
                  <TableRow
                    key={key}
                    className={cn(
                      selected.has(key) && "bg-primary/5",
                      verdict?.verdict === "keep" && "bg-green-50/60"
                    )}
                  >
                    <TableCell>
                      <Checkbox
                        checked={selected.has(key)}
                        onCheckedChange={() => toggleItem(key)}
                      />
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-col gap-1">
                        <span className="font-medium text-sm">{item.skill_name}</span>
                        <PoolBadge pool={item.pool} />
                      </div>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{item.source || "—"}</TableCell>
                    <TableCell>
                      <span className={cn("text-sm", confidenceColor(item.confidence_score))}>
                        {item.confidence_score.toFixed(3)}
                      </span>
                    </TableCell>
                    <TableCell className="text-sm">
                      {item.times_rejected ?? item.run_count ?? 1}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {item.category || "—"}
                      {item.subcategory ? ` / ${item.subcategory}` : ""}
                    </TableCell>
                    <TableCell>
                      {verdict ? (
                        <div className="flex flex-col gap-0.5">
                          <span className={cn(
                            "text-xs font-semibold",
                            verdict.verdict === "keep" ? "text-green-700" : "text-muted-foreground"
                          )}>
                            {verdict.verdict === "keep" ? "Keep" : "Skip"}
                          </span>
                          <span className="text-xs text-muted-foreground">{verdict.reason}</span>
                        </div>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </Card>
      )}
    </div>
  );
}
