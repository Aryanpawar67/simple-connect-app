import { useState } from "react";
import AppLayout from "@/components/AppLayout";
import SkillScraperPage from "@/pages/SkillScraperPage";
import ChangelogScraperPage from "@/pages/ChangelogScraperPage";

const Index = () => {
  const [activeTool, setActiveTool] = useState<"scraper" | "changelog">("scraper");

  return (
    <AppLayout activeTool={activeTool} onToolChange={setActiveTool}>
      {activeTool === "scraper" ? <SkillScraperPage /> : <ChangelogScraperPage />}
    </AppLayout>
  );
};

export default Index;
