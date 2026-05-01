import type { Status } from "../types";

const styles: Record<Status, string> = {
  idle: "bg-slate-100 text-slate-700",
  computing: "bg-amber-100 text-amber-800",
  ready: "bg-emerald-100 text-emerald-800",
  error: "bg-red-100 text-red-800",
};

const labels: Record<Status, string> = {
  idle: "Не запущено",
  computing: "Расчёт идёт…",
  ready: "Готово",
  error: "Ошибка",
};

export function StateBadge({ status }: { status: Status }) {
  return <span className={`badge ${styles[status]}`}>{labels[status]}</span>;
}

export function KzBadge({ kz }: { kz: number }) {
  let cls = "bg-slate-100 text-slate-700";
  if (kz >= 0.99) cls = "bg-emerald-100 text-emerald-800";
  else if (kz >= 0.7) cls = "bg-lime-100 text-lime-800";
  else if (kz >= 0.3) cls = "bg-amber-100 text-amber-800";
  else cls = "bg-red-100 text-red-800";
  return <span className={`badge ${cls}`}>kz = {kz.toFixed(2)}</span>;
}
