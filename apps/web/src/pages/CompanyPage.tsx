import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  api,
  fmtMoney,
  fmtNum,
  fmtPct,
  roleLabel,
  shortName,
} from "../api";
import { TinLink } from "../components/TinLink";
import type { CompanyProfileResponse } from "../types";
import { KzBadge } from "../components/StateBadge";

export default function CompanyPage() {
  const { bin } = useParams<{ bin: string }>();
  const [profile, setProfile] = useState<CompanyProfileResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!bin) return;
    setLoading(true);
    setErrMsg(null);
    setProfile(null);
    api
      .getCompany(bin)
      .then(setProfile)
      .catch((err) => setErrMsg(String(err)))
      .finally(() => setLoading(false));
  }, [bin]);

  if (loading) return <div className="text-slate-500">Загрузка профиля…</div>;
  if (errMsg)
    return (
      <div className="card border-red-200 bg-red-50 text-red-800">
        <div className="font-semibold">Не удалось получить профиль:</div>
        <div className="mt-1 text-sm">{errMsg}</div>
        <Link to="/home" className="mt-3 inline-block text-teal-700 underline">
          ← На главную
        </Link>
      </div>
    );
  if (!profile) return null;

  const { card, backward, forward } = profile;
  return (
    <div className="space-y-6">
      <Link
        to="/cases"
        className="text-sm text-slate-500 hover:text-slate-700"
      >
        ← К списку кейсов
      </Link>

      {/* Card */}
      <section className="card">
        <div className="flex items-start justify-between flex-wrap gap-4">
          <div>
            <div className="text-xs uppercase tracking-wide text-slate-500">
              {roleLabel(card.role)}
            </div>
            <h1 className="mt-1 text-2xl font-bold text-slate-900">
              {card.name ?? "(без имени)"}
            </h1>
            <div className="mt-1 font-mono text-sm text-slate-500">
              BIN {card.tin}
            </div>
          </div>
          <div className="flex flex-col items-end gap-2">
            <KzBadge kz={card.kz} />
            <div className="text-3xl font-bold text-slate-900">
              {fmtPct(card.kz * 100)}
            </div>
            <div className="text-xs text-slate-500">индекс КС</div>
          </div>
        </div>

        <div className="mt-6 grid grid-cols-1 md:grid-cols-4 gap-4">
          <Stat label="Закупки" value={fmtMoney(card.purchases)} hint={`${card.in_degree} поставщиков`} />
          <Stat label="Продажи" value={fmtMoney(card.sales)} hint={`${card.out_degree} покупателей`} />
          <Stat
            label="Импорт в продажах"
            value={fmtMoney(card.import_value_in_sales)}
            tone={card.import_value_in_sales > 0 ? "amber" : "emerald"}
          />
          <Stat
            label="Резидентность"
            value={
              card.is_non_resident === true
                ? "Нерезидент"
                : card.is_non_resident === false
                  ? "Резидент"
                  : "Неизвестно"
            }
            tone={card.is_non_resident ? "amber" : "emerald"}
          />
        </div>
      </section>

      {/* Backward */}
      <section className="card">
        <h2 className="font-semibold text-slate-900">
          Откуда приходит стоимость — цепочка поставщиков
        </h2>
        <p className="mt-1 text-xs text-slate-500 max-w-3xl">
          Прямые поставщики компании, их собственные поставщики, и так до
          самого начала цепочки. Здесь видно, через каких именно контрагентов
          к компании приходит казахстанская и импортная стоимость.
        </p>
        {!backward.applicable ? (
          <p className="mt-2 text-sm text-slate-600">{backward.reason}</p>
        ) : (
          <>
            {backward.direct_import &&
              backward.direct_import.non_resident_suppliers_count > 0 && (
                <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                  ⚠ Прямой импорт от нерезидентов:{" "}
                  <strong>{fmtMoney(backward.direct_import.value)}</strong> (
                  {fmtPct(backward.direct_import.share * 100, 1)} закупок) от{" "}
                  {backward.direct_import.non_resident_suppliers_count}{" "}
                  поставщика(-ов).
                </div>
              )}

            <h3 className="mt-4 text-sm font-semibold text-slate-700">
              Топ-{backward.suppliers.length} поставщиков из{" "}
              {backward.suppliers_total}
            </h3>
            <table className="mt-2 w-full text-sm">
              <thead className="text-xs uppercase tracking-wide text-slate-500 border-b border-slate-200">
                <tr className="text-left">
                  <th className="py-2 pr-4 font-medium">BIN</th>
                  <th className="py-2 pr-4 font-medium">Название</th>
                  <th className="py-2 pr-4 font-medium text-right">Сумма</th>
                  <th className="py-2 pr-4 font-medium text-right">Доля</th>
                  <th className="py-2 pr-4 font-medium text-right">kz</th>
                  <th className="py-2 pr-4 font-medium">Вид</th>
                </tr>
              </thead>
              <tbody>
                {backward.suppliers.map((s) => (
                  <tr
                    key={s.tin}
                    className="border-b border-slate-100 last:border-0 hover:bg-slate-50"
                  >
                    <td className="py-2 pr-4">
                      <TinLink tin={s.tin} />
                    </td>
                    <td className="py-2 pr-4">{shortName(s.name, 35)}</td>
                    <td className="py-2 pr-4 text-right">
                      {fmtMoney(s.weight)}
                    </td>
                    <td className="py-2 pr-4 text-right">
                      {fmtPct(s.share * 100, 1)}
                    </td>
                    <td className="py-2 pr-4 text-right font-mono">
                      {s.kz.toFixed(2)}
                    </td>
                    <td className="py-2 pr-4">
                      {s.is_non_resident && (
                        <span className="badge bg-amber-100 text-amber-800">
                          нерезидент
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {backward.layers.length > 0 && (
              <div className="mt-4">
                <h3 className="text-sm font-semibold text-slate-700 mb-2">
                  По слоям вверх
                </h3>
                <Layers
                  rows={backward.layers.map((l) => ({
                    level: l.level,
                    size: l.size,
                    secondary: `нерезидентов: ${l.non_resident_count}`,
                    avg_kz: l.avg_kz,
                  }))}
                />
                <div className="mt-2 text-xs text-slate-500">
                  Всего в backward-конусе: {fmtNum(backward.cone_size)} компаний
                  ({fmtPct(backward.cone_share * 100, 2)} графа)
                </div>
              </div>
            )}
          </>
        )}
      </section>

      {/* Forward */}
      <section className="card">
        <h2 className="font-semibold text-slate-900">
          Куда расходится продукция — цепочка покупателей
        </h2>
        <p className="mt-1 text-xs text-slate-500 max-w-3xl">
          Прямые покупатели компании, их покупатели, и так до конечных
          потребителей. Здесь видно, через каких именно контрагентов её
          импортная и казахстанская составляющая расходится по экономике
          и где в итоге «оседает».
        </p>
        {!forward.applicable ? (
          <p className="mt-2 text-sm text-slate-600">{forward.reason}</p>
        ) : (
          <>
            <h3 className="mt-3 text-sm font-semibold text-slate-700">
              Топ-{forward.customers.length} покупателей из{" "}
              {forward.customers_total}
            </h3>
            <table className="mt-2 w-full text-sm">
              <thead className="text-xs uppercase tracking-wide text-slate-500 border-b border-slate-200">
                <tr className="text-left">
                  <th className="py-2 pr-4 font-medium">BIN</th>
                  <th className="py-2 pr-4 font-medium">Название</th>
                  <th className="py-2 pr-4 font-medium text-right">Закупил</th>
                  <th className="py-2 pr-4 font-medium text-right">
                    Доля у него
                  </th>
                  <th className="py-2 pr-4 font-medium text-right">kz</th>
                </tr>
              </thead>
              <tbody>
                {forward.customers.map((c) => (
                  <tr
                    key={c.tin}
                    className="border-b border-slate-100 last:border-0 hover:bg-slate-50"
                  >
                    <td className="py-2 pr-4">
                      <TinLink tin={c.tin} />
                    </td>
                    <td className="py-2 pr-4">{shortName(c.name, 35)}</td>
                    <td className="py-2 pr-4 text-right">
                      {fmtMoney(c.weight)}
                    </td>
                    <td className="py-2 pr-4 text-right">
                      {fmtPct(c.share_in_buyer * 100, 1)}
                    </td>
                    <td className="py-2 pr-4 text-right font-mono">
                      {c.kz.toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {forward.layers.length > 0 && (
              <div className="mt-4">
                <h3 className="text-sm font-semibold text-slate-700 mb-2">
                  По слоям вниз
                </h3>
                <Layers
                  rows={forward.layers.map((l) => ({
                    level: l.level,
                    size: l.size,
                    secondary:
                      l.end_consumers > 0
                        ? `конечных потребителей: ${l.end_consumers}, продажи: ${fmtMoney(l.layer_sales)}`
                        : `продажи: ${fmtMoney(l.layer_sales)}`,
                    avg_kz: l.avg_kz,
                  }))}
                />
                <div className="mt-2 text-xs text-slate-500">
                  Всего в forward-конусе: {fmtNum(forward.cone_size)} компаний (
                  {fmtPct(forward.cone_share * 100, 2)} графа)
                </div>
              </div>
            )}
          </>
        )}
      </section>
    </div>
  );
}

function Stat({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "amber" | "emerald";
}) {
  const toneClass =
    tone === "amber"
      ? "text-amber-700"
      : tone === "emerald"
        ? "text-emerald-700"
        : "text-slate-900";
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className={`mt-1 text-lg font-semibold ${toneClass}`}>{value}</div>
      {hint && <div className="text-xs text-slate-500 mt-0.5">{hint}</div>}
    </div>
  );
}

function Layers({
  rows,
}: {
  rows: { level: number; size: number; secondary: string; avg_kz: number }[];
}) {
  return (
    <ol className="space-y-1.5">
      {rows.map((r) => (
        <li
          key={r.level}
          className="flex items-center gap-3 rounded border border-slate-200 px-3 py-1.5 text-sm"
        >
          <span className="font-mono text-slate-500 w-16">Слой {r.level}</span>
          <span className="font-medium">{fmtNum(r.size)} компаний</span>
          <span className="text-slate-500 text-xs flex-1">{r.secondary}</span>
          <KzBadge kz={r.avg_kz} />
        </li>
      ))}
    </ol>
  );
}
