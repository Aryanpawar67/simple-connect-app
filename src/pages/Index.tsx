import { useState } from "react";
import AppLayout from "@/components/AppLayout";
import SkillScraperPage from "@/pages/SkillScraperPage";
import ChangelogScraperPage from "@/pages/ChangelogScraperPage";
import TaxonomyManagerPage from "@/pages/TaxonomyManagerPage";

const Index = () => {
  const [activeTool, setActiveTool] = useState<"scraper" | "changelog" | "taxonomy">("scraper");

  return (
    <AppLayout activeTool={activeTool} onToolChange={setActiveTool}>
      {activeTool === "scraper" && <SkillScraperPage onGoToTaxonomy={() => setActiveTool("taxonomy")} />}
      {activeTool === "changelog" && <ChangelogScraperPage />}
      {activeTool === "taxonomy" && <TaxonomyManagerPage />}
    </AppLayout>
  );
};

export default Index;
