import {
  ChartNoAxesCombined,
  ChartPie,
  LayoutDashboard,
  Newspaper,
  ScrollText,
  TableProperties,
} from "lucide-react";

export type ModuleId = "review" | "performance" | "news" | "constituents" | "analytics" | "footnotes";

const modules = [
  { id: "review", label: "Review", icon: LayoutDashboard },
  { id: "performance", label: "Historical Performance", icon: ChartNoAxesCombined },
  { id: "news", label: "Company News", icon: Newspaper },
  { id: "constituents", label: "Constituent Performance", icon: TableProperties },
  { id: "analytics", label: "Final Analytics", icon: ChartPie },
  { id: "footnotes", label: "Footnotes & Disclosures", icon: ScrollText },
] as const;

interface ModuleNavProps {
  active: ModuleId;
  onSelect: (id: ModuleId) => void;
  states: Partial<Record<ModuleId, "ready" | "attention" | "empty">>;
}

export function ModuleNav({ active, onSelect, states }: ModuleNavProps) {
  return (
    <nav className="module-nav" aria-label="Report modules">
      <div className="module-nav-heading">Report modules</div>
      {modules.map(({ id, label, icon: Icon }, index) => (
        <button
          key={id}
          className={active === id ? "module-link active" : "module-link"}
          onClick={() => onSelect(id)}
          aria-current={active === id ? "page" : undefined}
        >
          <span className="module-index">{String(index + 1).padStart(2, "0")}</span>
          <Icon size={18} strokeWidth={1.8} aria-hidden="true" />
          <span>{label}</span>
          <i className={`module-state ${states[id] ?? "empty"}`} aria-hidden="true" />
        </button>
      ))}
    </nav>
  );
}