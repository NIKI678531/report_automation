import {
  ChartNoAxesCombined,
  ChartPie,
  LayoutDashboard,
  Newspaper,
  ScrollText,
  TableProperties,
} from "lucide-react";
import { REPORT_MODULES, type ModuleId } from "../reportModules";
import { useLocale } from "../i18n";

const moduleIcons = {
  review: LayoutDashboard,
  performance: ChartNoAxesCombined,
  news: Newspaper,
  constituents: TableProperties,
  analytics: ChartPie,
  footnotes: ScrollText,
};

export type { ModuleId } from "../reportModules";

interface ModuleNavProps {
  active: ModuleId;
  onSelect: (id: ModuleId) => void;
  states: Partial<Record<ModuleId, "ready" | "attention" | "empty">>;
}

export function ModuleNav({ active, onSelect, states }: ModuleNavProps) {
  const { t } = useLocale();
  const labels: Record<ModuleId, string> = {
    review: t("review"), performance: t("historicalPerformance"), news: t("companyNews"),
    constituents: t("constituentPerformance"), analytics: t("finalAnalytics"), footnotes: t("footnotes"),
  };
  return (
    <nav className="module-nav" aria-label={t("reportModules")}>
      <div className="module-nav-heading">{t("reportModules")}</div>
      {REPORT_MODULES.map(({ id, label, pageLabel }) => {
        const Icon = moduleIcons[id];
        return (
          <button
            key={id}
            className={active === id ? "module-link active" : "module-link"}
            onClick={() => onSelect(id)}
            aria-current={active === id ? "page" : undefined}
          >
            <span className="module-index">{pageLabel}</span>
            <Icon size={18} strokeWidth={1.8} aria-hidden="true" />
            <span>{labels[id] ?? label}</span>
            <i className={`module-state ${states[id] ?? "empty"}`} aria-hidden="true" />
          </button>
        );
      })}
    </nav>
  );
}
