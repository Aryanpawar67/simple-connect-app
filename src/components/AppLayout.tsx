import { useState } from "react";
import { Search, GitCompareArrows, Menu, X, Database } from "lucide-react";
import { cn } from "@/lib/utils";

interface AppLayoutProps {
  children: React.ReactNode;
  activeTool: "scraper" | "changelog" | "taxonomy";
  onToolChange: (tool: "scraper" | "changelog" | "taxonomy") => void;
}

const navItems = [
  {
    id: "scraper" as const,
    label: "Skill Discovery",
    description: "Find trending skills",
    icon: Search,
  },
  {
    id: "changelog" as const,
    label: "Taxonomy Changelog",
    description: "Track official changes",
    icon: GitCompareArrows,
  },
  {
    id: "taxonomy" as const,
    label: "Taxonomy Manager",
    description: "Merge & manage master list",
    icon: Database,
  },
];

const AppLayout = ({ children, activeTool, onToolChange }: AppLayoutProps) => {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Mobile overlay */}
      {mobileOpen && (
        <div
          className="fixed inset-0 bg-foreground/20 z-40 lg:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={cn(
          "fixed lg:static inset-y-0 left-0 z-50 w-64 bg-sidebar flex flex-col transition-transform duration-200",
          mobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
        )}
      >
        <div className="p-5 border-b border-sidebar-border">
          <h1 className="text-lg font-bold text-sidebar-primary-foreground tracking-tight">
            TaxoTrack
          </h1>
          <p className="text-xs text-sidebar-muted mt-0.5">
            Skill Discovery & Taxonomy Management
          </p>
        </div>

        <nav className="flex-1 p-3 space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = activeTool === item.id;
            return (
              <button
                key={item.id}
                onClick={() => {
                  onToolChange(item.id);
                  setMobileOpen(false);
                }}
                className={cn(
                  "w-full flex items-start gap-3 px-3 py-3 rounded-lg text-left transition-colors",
                  isActive
                    ? "bg-sidebar-accent text-sidebar-accent-foreground"
                    : "text-sidebar-foreground hover:bg-sidebar-accent/50"
                )}
              >
                <Icon className="w-5 h-5 mt-0.5 shrink-0" />
                <div>
                  <div className="text-sm font-medium">{item.label}</div>
                  <div className="text-xs text-sidebar-muted mt-0.5">
                    {item.description}
                  </div>
                </div>
              </button>
            );
          })}
        </nav>

        <div className="p-4 border-t border-sidebar-border">
          <div className="text-xs text-sidebar-muted">
            No login required · Internal tool
          </div>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 flex flex-col overflow-hidden">
        <header className="h-14 border-b flex items-center px-4 lg:px-6 shrink-0">
          <button
            onClick={() => setMobileOpen(true)}
            className="lg:hidden mr-3 p-1.5 rounded-md hover:bg-secondary"
          >
            <Menu className="w-5 h-5" />
          </button>
          <h2 className="text-base font-semibold">
            {navItems.find((i) => i.id === activeTool)?.label}
          </h2>
        </header>
        <div className="flex-1 overflow-y-auto p-4 lg:p-8">{children}</div>
      </main>
    </div>
  );
};

export default AppLayout;
