import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, fmtMoney, fmtNum, fmtPct } from "../api";
import type { AggregateResponse, StateResponse } from "../types";
import { StateBadge } from "../components/StateBadge";
import { Tabs } from "../components/Tabs";
import CompanyView from "../components/CompanyView";

const DOCS_BASE = import.meta.env.VITE_DOCS_URL || "http://localhost:8080";
const DOCS_URL = `${DOCS_BASE}/executive-summary/`;

type TabId = "economy" | "company";

export default function HomePage() {
  const [state, setState] = useState<StateResponse | null>(null);
  const [aggregate, setAggregate] = useState<AggregateResponse | null>(null);
  const [days, setDays] = useState(90);
  const [pending, setPending] = useState(false);
  const [errMsg, setErrMsg] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabId>("economy");

  // Polling state when computing
  useEffect(() => {
    let timer: number | undefined;

    async function poll() {
      try {
        const s = await api.getState();
        setState(s);
        if (s.status === "ready") {
          try {
            setAggregate(await api.getAggregate());
          } catch {
            /* noop */
          }
        }
        if (s.status === "computing") {
          timer = window.setTimeout(poll, 2000);
        }
      } catch (err) {
        setErrMsg(String(err));
      }
    }

    poll();
    return () => {
      if (timer) window.clearTimeout(timer);
    };
  }, []);

  async function onRecompute() {
    setPending(true);
    setErrMsg(null);
    setAggregate(null);
    try {
      // Запускаем расчёт. Запрос блокирующий (~80 сек).
      // Параллельно поллим /state каждые 2 секунды,
      // чтобы пользователь видел статус.
      let stopped = false;
      const pollState = async () => {
        if (stopped) return;
        try {
          const s = await api.getState();
          setState(s);
        } catch {
          /* noop */
        }
        if (!stopped) window.setTimeout(pollState, 2000);
      };
      window.setTimeout(pollState, 500);

      const finalState = await api.recompute(days, true);
      stopped = true;
      setState(finalState);
      if (finalState.status === "ready") {
        setAggregate(await api.getAggregate());
      } else if (finalState.status === "error") {
        setErrMsg(finalState.error ?? "Неизвестная ошибка");
      }
    } catch (err) {
      setErrMsg(String(err));
    } finally {
      setPending(false);
    }
  }

  const meta = state?.meta;

  return (
    <div className="space-y-8">
      <section>
        <h1 className="text-3xl font-bold tracking-tight text-slate-900">
          Индекс казахстанского содержания
        </h1>
        <p className="mt-2 text-slate-600 max-w-3xl">
          Система оценивает реальную долю казахстанского труда и материалов
          в B2B-сделках по данным электронных счетов-фактур (ЭСФ),
          прослеживая полные цепочки поставок и отделяя «переупакованный»
          импорт от подлинно казахстанской продукции.
        </p>
        <p className="mt-2 text-slate-600 max-w-3xl">
          Что и как мы считаем — в{" "}
          <a
            href={DOCS_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="text-teal-700 underline underline-offset-2 hover:text-teal-900 font-medium"
          >
            кратком описании проекта
          </a>{" "}
          (без технических деталей).
        </p>
      </section>

      <Tabs
        active={activeTab}
        onChange={(id) => setActiveTab(id as TabId)}
        tabs={[
          { id: "economy", label: "Срез по экономике" },
          { id: "company", label: "Расчёт по компании" },
        ]}
      />

      {state?.readonly && (
        <section className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <strong className="font-semibold">Демо-режим (snapshot).</strong>{" "}
          Сервис работает на сохранённом снимке графа от{" "}
          {state.snapshot_saved_at
            ? new Date(state.snapshot_saved_at).toLocaleString("ru-RU", {
                dateStyle: "long",
                timeStyle: "short",
              })
            : "—"}
          . Пересчёт периода и подключение к ЭСФ/VoltDB в этом режиме
          отключены — все остальные запросы (по компании, кейсы, агрегат)
          доступны в полном объёме.
        </section>
      )}

      {activeTab === "company" && <CompanyView state={state} />}

      {activeTab === "economy" && (
        <>
      {/* Controls */}
      <section className="card">
        <div className="flex flex-wrap items-end gap-4">
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">
              Период (дней)
              <span
                className="ml-1 text-slate-400 cursor-help"
                title="За какое количество последних дней собирать B2B-сделки и считать долю казахстанского содержания. Например, 90 дней = квартал."
              >
                (i)
              </span>
            </label>
            <input
              type="number"
              min={1}
              max={3650}
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              className="w-32 rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500"
              disabled={pending || state?.status === "computing" || !!state?.readonly}
            />
          </div>
          <button
            onClick={onRecompute}
            disabled={pending || state?.status === "computing" || !!state?.readonly}
            className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
            title={state?.readonly ? "Демо-режим: пересчёт недоступен" : undefined}
          >
            {state?.readonly
              ? "Пересчёт недоступен (snapshot)"
              : state?.status === "computing"
                ? "Расчёт идёт…"
                : "Пересчитать индекс"}
          </button>
          <div className="ml-auto flex items-center gap-3">
            <span className="text-sm text-slate-500">Статус:</span>
            <StateBadge status={state?.status ?? "idle"} />
            {state?.duration_seconds != null && (
              <span className="text-sm text-slate-500">
                ({state.duration_seconds.toFixed(1)} с)
              </span>
            )}
          </div>
        </div>
        {errMsg && (
          <div className="mt-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            <strong className="font-semibold">Ошибка:</strong>{" "}
            <pre className="mt-1 whitespace-pre-wrap font-mono text-xs">
              {errMsg}
            </pre>
          </div>
        )}
        {state?.status === "computing" && (
          <p className="mt-4 text-sm text-amber-700">
            Полный прогон занимает ~80 секунд: 5 с MySQL, 25 с VoltDB lookup, 50
            с fixed-point итерации.
          </p>
        )}
      </section>

      {/* Aggregate */}
      {aggregate && state?.status === "ready" && (
        <section>
          <div className="flex items-baseline justify-between flex-wrap gap-2 mb-3">
            <h2 className="text-xl font-semibold text-slate-900">
              Агрегат по экономике
            </h2>
            {meta?.date_from && meta?.date_to && (
              <span className="text-sm text-slate-500 font-mono">
                {meta.date_from} → {meta.date_to}
                <span className="ml-2 text-slate-400">
                  ({meta.days} дней)
                </span>
              </span>
            )}
          </div>

          <div className="rounded-md bg-sky-50 border border-sky-200 p-4 mb-4 text-sm text-sky-900">
            <strong className="font-semibold">Что показывают эти цифры.</strong>{" "}
            Доля импорта в B2B-обороте, задокументированном через ЭСФ
            (электронные счета-фактуры) за выбранный период.
            <span className="block mt-2 text-sky-800">
              Не учтены: розничная торговля (B2C), прямой импорт через таможню
              без выписки ЭСФ, услуги через зарубежные платёжные системы,
              государственные субсидии.
            </span>
            <span className="block mt-2 text-sky-700 italic">
              Это <strong>не</strong> «доля импорта в ВВП», это «доля импорта в
              задокументированном B2B-обороте за период» — другая величина.
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="card">
              <div className="text-xs uppercase tracking-wide text-slate-500">
                Совокупный оборот
              </div>
              <div className="mt-1 text-2xl font-bold text-slate-900">
                {fmtMoney(aggregate.total_sales)}
              </div>
              <div className="mt-1 text-xs text-slate-500">
                {fmtNum(aggregate.sellers_count)} компаний-продавцов
              </div>
              <div
                className="mt-2 text-xs text-slate-500 leading-relaxed"
                title="Сумма всех ЭСФ-документов, по которым в этом периоде кто-то кому-то продал"
              >
                = сумма всех B2B-продаж в периоде по данным ЭСФ
              </div>
            </div>
            <div className="card border-amber-200">
              <div className="text-xs uppercase tracking-wide text-amber-700">
                Импортная составляющая
              </div>
              <div className="mt-1 text-2xl font-bold text-amber-800">
                {fmtMoney(aggregate.import_value)}
              </div>
              <div className="mt-1 text-xs text-amber-700">
                {fmtPct(aggregate.import_share_pct)} от оборота
              </div>
              <div
                className="mt-2 text-xs text-amber-700/80 leading-relaxed"
                title="Сумма продаж × (1 − индекс КС) по всем компаниям"
              >
                = сколько денег за период оплачено импортным товарам
                и услугам через цепочки поставок
              </div>
            </div>
            <div className="card border-emerald-200">
              <div className="text-xs uppercase tracking-wide text-emerald-700">
                Казахстанская составляющая
              </div>
              <div className="mt-1 text-2xl font-bold text-emerald-800">
                {fmtMoney(aggregate.domestic_value)}
              </div>
              <div className="mt-1 text-xs text-emerald-700">
                {fmtPct(aggregate.domestic_share_pct)} от оборота
              </div>
              <div
                className="mt-2 text-xs text-emerald-700/80 leading-relaxed"
                title="Сумма продаж × индекс КС по всем компаниям"
              >
                = реально казахстанский труд и материалы в оплаченных
                товарах и услугах
              </div>
            </div>
          </div>
        </section>
      )}

      {/* Structure of the graph — explains why aggregate covers only N sellers */}
      {meta && aggregate && state?.status === "ready" && (
        <section className="card border-slate-200">
          <h3 className="font-semibold text-slate-900">
            Кто попал в этот срез экономики
          </h3>
          <p className="text-xs text-slate-500 mt-1 mb-3">
            За период через электронные счета-фактуры зафиксированы B2B-сделки
            между этими компаниями. У тех, кто что-то продавал, мы считаем
            индекс казахстанского содержания с учётом всей цепочки их
            поставщиков. У тех, кто только покупал — индекс не считаем: им
            некому передавать свою долю КС вниз по цепочке.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
            <div>
              <div className="text-xs uppercase tracking-wide text-slate-500">
                Всего компаний в срезе
              </div>
              <div className="mt-1 text-xl font-bold">
                {fmtNum(meta.nodes ?? 0)}
              </div>
              <div className="text-xs text-slate-500 mt-1">
                любое участие в B2B-сделке за период — как продавец
                или покупатель
              </div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wide text-slate-500">
                Из них реально продавали
              </div>
              <div className="mt-1 text-xl font-bold text-slate-900">
                {fmtNum(aggregate.sellers_count)}
              </div>
              <div className="text-xs text-slate-500 mt-1">
                для них рассчитан индекс КС с учётом всей цепочки
                поставщиков
              </div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wide text-slate-500">
                Только покупали
              </div>
              <div className="mt-1 text-xl font-bold text-slate-900">
                {fmtNum(
                  Math.max(
                    0,
                    (meta.nodes ?? 0) - aggregate.sellers_count,
                  ),
                )}
              </div>
              <div className="text-xs text-slate-500 mt-1">
                конечные потребители — на них «оседает» вся импортная
                и казахстанская стоимость, прошедшая по цепочкам
              </div>
            </div>
          </div>
        </section>
      )}

      {/* Meta */}
      {meta && state?.status === "ready" && (
        <section className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="card">
            <h3 className="font-semibold text-slate-900 mb-3">Срез данных</h3>
            <dl className="grid grid-cols-2 gap-y-2 text-sm">
              <dt className="text-slate-500">Период</dt>
              <dd className="font-mono">
                {meta.date_from} → {meta.date_to}
              </dd>
              <dt className="text-slate-500">Глубина</dt>
              <dd>{meta.days} дней</dd>
              <dt className="text-slate-500">Рёбер из MySQL</dt>
              <dd>{fmtNum(meta.raw_edges ?? 0)}</dd>
              <dt className="text-slate-500">Узлов в графе</dt>
              <dd>{fmtNum(meta.nodes ?? 0)}</dd>
              <dt className="text-slate-500">После фильтра</dt>
              <dd>{fmtNum(meta.edges_after_filter ?? 0)}</dd>
            </dl>
          </div>
          <div className="card">
            <h3 className="font-semibold text-slate-900 mb-3">
              Обогащение и расчёт
            </h3>
            <dl className="grid grid-cols-2 gap-y-2 text-sm">
              <dt className="text-slate-500">Резидентов</dt>
              <dd>
                {fmtNum(
                  (meta.voltdb?.resolved ?? 0) -
                    (meta.voltdb?.non_resident ?? 0),
                )}
              </dd>
              <dt className="text-slate-500">Нерезидентов</dt>
              <dd className="text-amber-700 font-medium">
                {fmtNum(meta.voltdb?.non_resident ?? 0)}
              </dd>
              <dt className="text-slate-500">Не в справочнике</dt>
              <dd>{fmtNum(meta.voltdb?.missing ?? 0)}</dd>
              <dt className="text-slate-500">Итераций</dt>
              <dd>
                {meta.compute?.iterations}
                {meta.compute?.converged ? "" : " (не сошлось)"}
              </dd>
            </dl>
          </div>
        </section>
      )}

      {/* Quick links */}
      {state?.status === "ready" && (
        <section className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Link
            to="/cases"
            className="card hover:border-teal-400 hover:shadow transition-all"
          >
            <h3 className="font-semibold text-slate-900">Меню кейсов →</h3>
            <p className="mt-1 text-sm text-slate-600">
              4 архетипа: импортёры, зависимые, чистые, в циклах.
            </p>
          </Link>
          <Link
            to="/search"
            className="card hover:border-teal-400 hover:shadow transition-all"
          >
            <h3 className="font-semibold text-slate-900">Поиск по BIN →</h3>
            <p className="mt-1 text-sm text-slate-600">
              Полный профиль любой компании из графа.
            </p>
          </Link>
          <a
            href={DOCS_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="card hover:border-teal-400 hover:shadow transition-all"
          >
            <h3 className="font-semibold text-slate-900">
              О проекте простыми словами ↗
            </h3>
            <p className="mt-1 text-sm text-slate-600">
              Что считаем, как считаем, какие ограничения. Без формул и кода.
            </p>
          </a>
        </section>
      )}

      {state?.status === "idle" && !pending && (
        <section className="card border-dashed text-center text-slate-500">
          Граф ещё не построен. Нажмите «Пересчитать индекс», чтобы начать.
        </section>
      )}
        </>
      )}
    </div>
  );
}
