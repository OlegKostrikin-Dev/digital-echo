type Tab = {
  id: string;
  label: string;
  badge?: string;
};

type Props = {
  tabs: Tab[];
  active: string;
  onChange: (id: string) => void;
};

export function Tabs({ tabs, active, onChange }: Props) {
  return (
    <div
      role="tablist"
      className="flex gap-1 border-b border-slate-200"
    >
      {tabs.map((t) => {
        const isActive = active === t.id;
        return (
          <button
            key={t.id}
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(t.id)}
            className={
              isActive
                ? "px-5 py-3 -mb-px border-b-2 border-teal-600 text-teal-700 font-semibold text-sm transition-colors"
                : "px-5 py-3 -mb-px border-b-2 border-transparent text-slate-600 hover:text-slate-900 hover:border-slate-300 text-sm transition-colors"
            }
          >
            {t.label}
            {t.badge && (
              <span className="ml-2 inline-flex items-center px-2 py-0.5 rounded-full text-xs bg-teal-100 text-teal-800">
                {t.badge}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
