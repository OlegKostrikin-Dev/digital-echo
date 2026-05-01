import { useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  fmtMoney,
  fmtNum,
  fmtPct,
  roleLabel,
  shortName,
} from "../api";
import type {
  CompanyProfileResponse,
  StateResponse,
  SupplierRow,
} from "../types";
import { Gauge } from "./Gauge";
import { TinLink } from "./TinLink";

type Props = {
  state: StateResponse | null;
};

/**
 * Декомпозиция выручки компании по правилу:
 *   own_value_add = max(0, sales − purchases)   — если резидент,
 *   supplier_kz_value = kz × purchases          — sum(kz_i × pay_i) by algo
 *   supplier_import   = (1 − kz) × purchases    — sum((1−kz_i) × pay_i)
 *
 * В норме (sales >= purchases) три части в сумме = sales.
 * Edge cases:
 *   - non-resident: всё импорт, доли 0/0/100
 *   - sales == 0: декомпозиция не применима
 *   - purchases > sales: нормируем к purchases (запасы)
 */
type Breakdown = {
  applicable: boolean;
  reason?: string;
  /** доля 0..1 от выручки */
  ownPct: number;
  supplierKzPct: number;
  supplierImportPct: number;
  /** в тенге, абсолютные значения */
  ownValue: number;
  supplierKzValue: number;
  supplierImportValue: number;
  /** «эффективная» КС-доля выручки = own + supplierKz */
  effectiveKz: number;
  /** Заметка о специфике (non-resident, stock) */
  note?: string;
};

function computeBreakdown(card: CompanyProfileResponse["card"]): Breakdown {
  const sales = card.sales;
  const purchases = card.purchases;
  const kz = card.kz;
  const isNonResident = card.is_non_resident === true;

  if (sales <= 0) {
    return {
      applicable: false,
      reason:
        "У компании нет продаж в этом срезе — декомпозиция выручки неприменима.",
      ownPct: 0,
      supplierKzPct: 0,
      supplierImportPct: 0,
      ownValue: 0,
      supplierKzValue: 0,
      supplierImportValue: 0,
      effectiveKz: 0,
    };
  }

  if (isNonResident) {
    return {
      applicable: true,
      ownPct: 0,
      supplierKzPct: 0,
      supplierImportPct: 1,
      ownValue: 0,
      supplierKzValue: 0,
      supplierImportValue: sales,
      effectiveKz: 0,
      note: "Компания — нерезидент. Вся её выручка — это импорт, попадающий в экономику РК.",
    };
  }

  if (purchases <= 0) {
    return {
      applicable: true,
      ownPct: 1,
      supplierKzPct: 0,
      supplierImportPct: 0,
      ownValue: sales,
      supplierKzValue: 0,
      supplierImportValue: 0,
      effectiveKz: 1,
      note: "В графе нет поставщиков — компания работает на собственных ресурсах (или закупки идут вне ЭСФ).",
    };
  }

  // normal case
  const ownValue = Math.max(0, sales - purchases);
  const supplierKzValue = kz * purchases;
  const supplierImportValue = (1 - kz) * purchases;
  const total = ownValue + supplierKzValue + supplierImportValue;

  // если purchases > sales (накопление запасов), normalize по total
  const denom = Math.max(sales, total);
  const note =
    purchases > sales
      ? "Закупки превышают продажи в этом срезе (накопление запасов). Доли показаны относительно общего движения денег."
      : undefined;

  return {
    applicable: true,
    ownPct: ownValue / denom,
    supplierKzPct: supplierKzValue / denom,
    supplierImportPct: supplierImportValue / denom,
    ownValue,
    supplierKzValue,
    supplierImportValue,
    effectiveKz: (ownValue + supplierKzValue) / denom,
    note,
  };
}

/** Топ-1 «вредный» поставщик: даёт максимум абсолютного импорта в наши закупки. */
function findKeyImporter(
  suppliers: SupplierRow[],
): { row: SupplierRow; importValue: number } | null {
  let best: { row: SupplierRow; importValue: number } | null = null;
  for (const s of suppliers) {
    const v = s.weight * (1 - s.kz);
    if (!best || v > best.importValue) best = { row: s, importValue: v };
  }
  return best && best.importValue > 0 ? best : null;
}

export default function CompanyView({ state }: Props) {
  const [bin, setBin] = useState("");
  const [profile, setProfile] = useState<CompanyProfileResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  const ready = state?.status === "ready";
  const meta = state?.meta;

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const tin = bin.trim();
    if (!tin) return;
    setLoading(true);
    setErrMsg(null);
    setProfile(null);
    try {
      const data = await api.getCompany(tin);
      setProfile(data);
    } catch (err) {
      const msg = String(err);
      if (msg.includes("404")) {
        setErrMsg(
          `Компания с БИН ${tin} не найдена в текущем срезе графа. ` +
            `Возможно, у неё не было B2B-сделок через ЭСФ за этот период.`,
        );
      } else {
        setErrMsg(msg);
      }
    } finally {
      setLoading(false);
    }
  }

  if (!ready) {
    return (
      <div className="card border-dashed text-center text-slate-500 py-12">
        <p>Граф ещё не построен.</p>
        <p className="mt-2 text-sm">
          Перейдите на вкладку «Срез по экономике» и нажмите «Пересчитать
          индекс».
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* ----- Form ----- */}
      <section className="card">
        <h2 className="text-xl font-semibold text-slate-900">
          Расчёт индекса по конкретной компании
        </h2>
        <p className="mt-1 text-sm text-slate-600 max-w-2xl">
          Введите БИН компании, чтобы увидеть её индекс КС, разложение по
          источникам стоимости и состав поставщиков.
        </p>

        <form onSubmit={onSubmit} className="mt-5 space-y-4">
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">
              БИН компании
              <span
                className="ml-1 text-slate-400 cursor-help"
                title="12-значный бизнес-идентификационный номер из ЭСФ"
              >
                (i)
              </span>
            </label>
            <input
              type="text"
              inputMode="numeric"
              autoComplete="off"
              maxLength={12}
              placeholder="123456789012"
              value={bin}
              onChange={(e) => setBin(e.target.value.replace(/[^0-9]/g, ""))}
              className="w-full max-w-md rounded-md border border-slate-300 px-3 py-2.5 text-sm font-mono focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500"
              disabled={loading}
            />
          </div>

          <div className="rounded-md bg-slate-50 border border-slate-200 p-3 text-xs text-slate-600">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="font-medium text-slate-700">
                Период анализа
              </span>
              {meta?.date_from && meta?.date_to && (
                <span className="font-mono">
                  {meta.date_from} → {meta.date_to} ({meta.days} дней)
                </span>
              )}
            </div>
            <p className="mt-1.5">
              Применяется ко всему срезу. Изменить период →{" "}
              <span className="text-teal-700">
                вкладка «Срез по экономике»
              </span>
              .
            </p>
          </div>

          <button
            type="submit"
            disabled={loading || !bin.trim()}
            className="btn-primary w-full max-w-md justify-center disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? "Считаем…" : "▶ Запустить расчёт"}
          </button>
        </form>

        {errMsg && (
          <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
            {errMsg}
          </div>
        )}
      </section>

      {/* ----- Result ----- */}
      {profile && <CompanyResult profile={profile} />}
    </div>
  );
}

// ============================================================ Result block

function CompanyResult({ profile }: { profile: CompanyProfileResponse }) {
  const { card, backward } = profile;
  const breakdown = computeBreakdown(card);
  const keyImporter =
    backward.applicable && backward.suppliers.length > 0
      ? findKeyImporter(backward.suppliers)
      : null;
  const keyImporterImpactPct =
    keyImporter && card.sales > 0
      ? (keyImporter.importValue / card.sales) * 100
      : 0;

  return (
    <>
      {/* HERO: gauge + identity */}
      <section className="card">
        <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
          <span className="badge bg-slate-100 text-slate-700">
            {roleLabel(card.role)}
          </span>
          {card.is_non_resident === false && (
            <span className="badge bg-emerald-100 text-emerald-800">
              резидент РК
            </span>
          )}
          {card.is_non_resident === true && (
            <span className="badge bg-amber-100 text-amber-800">
              нерезидент
            </span>
          )}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-[auto,1fr] gap-6 items-center">
          <div className="flex flex-col items-center">
            <Gauge value={card.kz} caption="индекс КС" size={200} />
            <div className="mt-2 text-xs text-slate-500 text-center max-w-[200px]">
              формальный индекс по графу B2B-сделок (то же значение в «Срез по
              экономике» и «Кейсах»)
            </div>
          </div>

          <div>
            <h2 className="text-2xl font-bold text-slate-900">
              {card.name ?? "(название не определено)"}
            </h2>
            <div className="mt-1 font-mono text-sm text-slate-500">
              БИН {card.tin}
            </div>
            <div className="mt-3 text-sm text-slate-600 max-w-lg">
              Индекс показывает, какая доля стоимости закупок этой компании
              имеет казахстанскую природу с учётом всей цепочки поставщиков.
            </div>

            <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
              <dt
                className="text-slate-500"
                title="Сумма всех ЭСФ-документов, по которым компания покупала у других B2B-контрагентов в периоде"
              >
                Закупки за период
              </dt>
              <dd className="font-medium">{fmtMoney(card.purchases)}</dd>
              <dt
                className="text-slate-500"
                title="Сумма всех ЭСФ-документов, по которым компания продавала другим B2B-контрагентам в периоде"
              >
                Продажи за период
              </dt>
              <dd className="font-medium">{fmtMoney(card.sales)}</dd>
              <dt
                className="text-slate-500"
                title="Сколько разных компаний-контрагентов продали что-либо этой компании в периоде"
              >
                Поставщиков
              </dt>
              <dd>{fmtNum(card.in_degree)}</dd>
              <dt
                className="text-slate-500"
                title="Сколько разных компаний-контрагентов купили что-либо у этой компании в периоде"
              >
                Покупателей
              </dt>
              <dd>{fmtNum(card.out_degree)}</dd>
            </dl>
          </div>
        </div>

        {/* «Как рассчитывается» — раскрываемый блок */}
        <details className="mt-5 rounded-md bg-slate-50 border border-slate-200 px-4 py-3 text-sm group">
          <summary className="cursor-pointer font-medium text-slate-700 hover:text-slate-900 marker:text-slate-400">
            Как рассчитывается этот индекс — простыми словами
          </summary>
          <div className="mt-3 space-y-2 text-slate-700 leading-relaxed">
            <p>
              Индекс отвечает на простой экономический вопрос:
              <em>«Из каждого тенге, который компания заплатила своим
              поставщикам, какая часть в итоге пошла на казахстанский труд
              и материалы, а какая — за границу?»</em>
            </p>
            <p>
              <strong>1.</strong> Смотрим, у кого компания покупала за
              период — это её прямые поставщики.
            </p>
            <p>
              <strong>2.</strong> У каждого поставщика — свой индекс КС:
              100% если это чистый отечественный производитель, 0% если
              зарубежный поставщик, и что-то посередине, если он сам
              работает на смеси импортных и казахстанских материалов.
            </p>
            <p>
              <strong>3.</strong> Складываем «казахстанскую» часть денег по
              каждому поставщику (объём закупок × его индекс) и делим на
              общую сумму закупок — получаем долю казахстанского
              содержания всей цепочки.
            </p>
            <p className="pt-2 border-t border-slate-200">
              <strong>Что это значит на практике.</strong> Компания,
              работающая с чистыми отечественными поставщиками, получит
              высокий индекс. Если хотя бы часть закупок идёт через
              посредников, которые сами зависят от импорта — индекс ниже,
              причём ровно настолько, насколько эти проблемные поставки
              крупны.
            </p>
            <p className="text-xs text-slate-500 italic pt-1">
              Расчёт идёт по официальным электронным счетам-фактурам —
              первичным налоговым документам. На одних и тех же данных
              результат всегда одинаковый, и любую цифру можно проверить,
              открыв конкретного поставщика и пройдя по его цепочке вверх.
            </p>
          </div>
        </details>
      </section>

      {/* Effective KZ callout (when materially different from formal) */}
      {breakdown.applicable &&
        card.is_non_resident === false &&
        breakdown.effectiveKz - card.kz > 0.05 && (
          <section className="card border-emerald-200 bg-emerald-50">
            <div className="flex items-start gap-3">
              <span className="text-emerald-700 text-xl leading-none">●</span>
              <div className="flex-1 text-sm text-emerald-900">
                <div className="font-semibold mb-1">
                  Расширенная оценка с учётом собственной маржи:{" "}
                  {Math.round(breakdown.effectiveKz * 100)}%
                </div>
                <p className="text-emerald-900/90 leading-relaxed">
                  Формальный индекс <strong>{(card.kz * 100).toFixed(0)}%</strong>{" "}
                  показывает только долю казахстанской стоимости в{" "}
                  <strong>закупках</strong> компании. Если добавить собственную
                  добавленную стоимость, которая остаётся в РК (выручка минус
                  закупки = {fmtMoney(breakdown.ownValue)}, идёт на ФОТ, налоги
                  и прибыль), эффективная доля КС в выручке —{" "}
                  <strong>{Math.round(breakdown.effectiveKz * 100)}%</strong>.
                </p>
                <p className="mt-2 text-xs text-emerald-700 italic">
                  В агрегате по экономике используется формальный индекс — это
                  гарантирует, что цифры на разных страницах сходятся.
                  «Расширенная оценка» — для углублённого анализа конкретной
                  компании.
                </p>
              </div>
            </div>
          </section>
        )}

      {/* DECOMPOSITION */}
      {breakdown.applicable && (
        <section>
          <div className="flex items-baseline justify-between flex-wrap gap-2 mb-3">
            <h3 className="text-lg font-semibold text-slate-900">
              Структура выручки
            </h3>
            <span className="text-xs text-slate-500">
              на что разложена каждая 1 ₸ выручки этой компании
            </span>
          </div>

          {/* Stacked bar */}
          <div className="card">
            <div className="flex h-4 w-full overflow-hidden rounded-full bg-slate-100">
              <div
                className="bg-emerald-500"
                style={{ width: `${breakdown.ownPct * 100}%` }}
                title={`Собственный вклад: ${(breakdown.ownPct * 100).toFixed(1)}%`}
              />
              <div
                className="bg-emerald-300"
                style={{ width: `${breakdown.supplierKzPct * 100}%` }}
                title={`Вклад поставщиков (KZ часть): ${(breakdown.supplierKzPct * 100).toFixed(1)}%`}
              />
              <div
                className="bg-amber-400"
                style={{ width: `${breakdown.supplierImportPct * 100}%` }}
                title={`Импорт через поставщиков: ${(breakdown.supplierImportPct * 100).toFixed(1)}%`}
              />
            </div>
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">
              <LegendDot color="bg-emerald-500" label="Собственный вклад" />
              <LegendDot color="bg-emerald-300" label="Вклад поставщиков (KZ)" />
              <LegendDot color="bg-amber-400" label="Импорт через поставщиков" />
            </div>
          </div>

          {/* Two cards: own + supplier KZ */}
          <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="card border-emerald-200">
              <div className="flex items-baseline justify-between">
                <h4 className="font-semibold text-slate-900">
                  Собственный вклад
                </h4>
                <span className="text-xl font-bold text-emerald-700">
                  {(breakdown.ownPct * 100).toFixed(0)}%
                </span>
              </div>
              <div className="mt-1 text-sm text-slate-600">
                {fmtMoney(breakdown.ownValue)} — выручка за вычетом стоимости
                закупок.
              </div>
              <ul className="mt-3 space-y-1.5 text-sm">
                <li className="text-slate-700">
                  ФОТ граждан РК
                  <span className="ml-2 text-xs text-slate-400 italic">
                    в будущей версии — отдельной цифрой
                  </span>
                </li>
                <li className="text-slate-700">
                  Уплаченные налоги в РК
                  <span className="ml-2 text-xs text-slate-400 italic">
                    в будущей версии — отдельной цифрой
                  </span>
                </li>
                <li className="text-slate-700">
                  Прибыль и амортизация в РК
                </li>
              </ul>
            </div>

            <div className="card border-emerald-200">
              <div className="flex items-baseline justify-between">
                <h4 className="font-semibold text-slate-900">
                  Вклад поставщиков
                </h4>
                <span className="text-xl font-bold text-emerald-700">
                  {(breakdown.supplierKzPct * 100).toFixed(0)}%
                </span>
              </div>
              <div className="mt-1 text-sm text-slate-600">
                {fmtMoney(breakdown.supplierKzValue)} — казахстанская часть
                стоимости, переданная по цепочке контрагентов.
              </div>
              <p className="mt-3 text-sm text-slate-700">
                Каждый поставщик добавляет в эту сумму свою долю КС, взвешенную
                по объёму закупок у него.
              </p>
              <p className="mt-2 text-xs text-slate-500">
                Импортная часть закупок:{" "}
                <span className="text-amber-700 font-medium">
                  {fmtMoney(breakdown.supplierImportValue)}
                </span>{" "}
                ({(breakdown.supplierImportPct * 100).toFixed(1)}% выручки)
              </p>
            </div>
          </div>

          {breakdown.note && (
            <div className="mt-3 text-xs text-slate-500 italic">
              {breakdown.note}
            </div>
          )}

          <details className="mt-3 text-sm text-slate-600">
            <summary className="cursor-pointer text-slate-500 hover:text-slate-700 marker:text-slate-400">
              На что разложена выручка — простыми словами
            </summary>
            <div className="mt-2 space-y-1.5 leading-relaxed pl-2">
              <p>
                <strong>Собственный вклад.</strong> Это деньги, которые
                остаются внутри самой компании сверх того, что она потратила
                на закупки: зарплаты её работникам, уплаченные налоги,
                прибыль, амортизация оборудования. Всё это — деньги,
                остающиеся в казахстанской экономике.
              </p>
              <p>
                <strong>Вклад поставщиков (казахстанский).</strong> Из всех
                денег, которые компания заплатила своим поставщикам, — какая
                часть в итоге пошла на оплату казахстанского труда и
                материалов с учётом всей цепочки до них.
              </p>
              <p>
                <strong>Импорт через поставщиков.</strong> Зеркальная часть:
                сколько денег, заплаченных поставщикам, в итоге ушло за
                границу за импортные материалы и услуги — даже если прямой
                импорт у самой компании отсутствует.
              </p>
            </div>
          </details>
        </section>
      )}

      {/* COUNTERPARTS */}
      {backward.applicable && backward.suppliers.length > 0 && (
        <section>
          <h3 className="text-lg font-semibold text-slate-900 mb-3">
            Анализ контрагентов
          </h3>

          {keyImporter && keyImporterImpactPct > 0.5 && (
            <div className="card border-amber-300 bg-amber-50">
              <div className="flex items-start gap-3">
                <span className="text-amber-600 text-xl leading-none">💡</span>
                <div className="flex-1 text-sm text-amber-900">
                  <strong className="font-semibold">Инсайт.</strong>{" "}
                  Поставщик{" "}
                  <TinLink
                    tin={keyImporter.row.tin}
                    className="font-medium underline underline-offset-2 text-amber-900"
                  >
                    {shortName(keyImporter.row.name, 30)}
                  </TinLink>{" "}
                  (индекс КС{" "}
                  <span className="font-mono">
                    {(keyImporter.row.kz * 100).toFixed(0)}%
                  </span>
                  ) приносит{" "}
                  <strong>
                    {fmtMoney(keyImporter.importValue)} (
                    {keyImporterImpactPct.toFixed(1)}% выручки)
                  </strong>{" "}
                  импортной составляющей. Замена на казахстанского производителя
                  с высоким КС повысит ваш индекс.
                </div>
              </div>
            </div>
          )}

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

          <div className="card mt-3 overflow-x-auto">
            <h4 className="text-sm font-semibold text-slate-700 mb-2">
              Топ-{backward.suppliers.length} из {backward.suppliers_total}{" "}
              поставщиков
            </h4>
            <table className="w-full text-sm">
              <thead className="text-xs uppercase tracking-wide text-slate-500 border-b border-slate-200">
                <tr className="text-left">
                  <th className="py-2 pr-4 font-medium">Название</th>
                  <th className="py-2 pr-4 font-medium">БИН</th>
                  <th className="py-2 pr-4 font-medium text-right">
                    Объём закупок
                  </th>
                  <th className="py-2 pr-4 font-medium text-right">
                    Индекс поставщика
                  </th>
                  <th className="py-2 pr-4 font-medium text-right">
                    Импорт через него
                  </th>
                </tr>
              </thead>
              <tbody>
                {backward.suppliers.map((s) => {
                  const importContribution = s.weight * (1 - s.kz);
                  const impactPct =
                    card.sales > 0
                      ? (importContribution / card.sales) * 100
                      : 0;
                  return (
                    <tr
                      key={s.tin}
                      className="border-b border-slate-100 last:border-0 hover:bg-slate-50"
                    >
                      <td className="py-2 pr-4">
                        <TinLink
                          tin={s.tin}
                          className="text-slate-900 hover:text-teal-700 underline underline-offset-2 decoration-slate-300 hover:decoration-teal-600"
                        >
                          {shortName(s.name, 30)}
                        </TinLink>
                        {s.is_non_resident && (
                          <span className="ml-2 badge bg-amber-100 text-amber-800 text-xs">
                            нерезидент
                          </span>
                        )}
                      </td>
                      <td className="py-2 pr-4">
                        <TinLink
                          tin={s.tin}
                          className="font-mono text-xs text-slate-500 underline-offset-2"
                        />
                      </td>
                      <td className="py-2 pr-4 text-right">
                        {fmtMoney(s.weight)}
                      </td>
                      <td className="py-2 pr-4 text-right">
                        <KzPill kz={s.kz} />
                      </td>
                      <td className="py-2 pr-4 text-right">
                        {importContribution > 0 ? (
                          <span className="text-amber-700 font-medium">
                            {fmtMoney(importContribution)}
                            <span className="ml-1 text-xs text-slate-500">
                              ({impactPct.toFixed(1)}%)
                            </span>
                          </span>
                        ) : (
                          <span className="text-slate-400">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            <div className="mt-2 grid grid-cols-1 sm:grid-cols-3 gap-x-4 gap-y-1 text-xs text-slate-500 leading-relaxed">
              <div>
                <strong className="text-slate-600">Объём закупок</strong> —
                сколько компания заплатила этому поставщику за период.
              </div>
              <div>
                <strong className="text-slate-600">Индекс поставщика</strong> —
                его собственная доля казахстанского содержания: насколько
                его собственная цепочка опирается на отечественное
                производство.
              </div>
              <div>
                <strong className="text-slate-600">Импорт через него</strong>{" "}
                — какая часть денег, заплаченных этому поставщику, в итоге
                ушла за границу: он сам докупил импорт, чтобы выполнить
                заказ.
              </div>
            </div>

            <div className="mt-3 text-xs text-slate-500">
              Полный профиль с цепочками вверх и вниз —{" "}
              <Link
                to={`/company/${card.tin}`}
                className="text-teal-700 underline underline-offset-2"
              >
                открыть страницу компании
              </Link>
              .
            </div>
          </div>
        </section>
      )}

      {/* ACTIONS */}
      <section className="card bg-slate-50 border-slate-200">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap gap-2">
            <DemoBtn icon="✈" label="Отправить на тендерную площадку" />
            <DemoBtn icon="⬇" label="Скачать выписку (PDF)" />
            <DemoBtn icon="🔍" label="Проверить алгоритм (Open Source)" />
          </div>
          <span className="badge bg-amber-100 text-amber-800">
            функционал в разработке
          </span>
        </div>
      </section>
    </>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`inline-block w-2.5 h-2.5 rounded-sm ${color}`} />
      <span>{label}</span>
    </span>
  );
}

function KzPill({ kz }: { kz: number }) {
  const pct = Math.round(kz * 100);
  const cls =
    kz >= 0.7
      ? "bg-emerald-100 text-emerald-800"
      : kz >= 0.4
        ? "bg-amber-100 text-amber-800"
        : "bg-red-100 text-red-800";
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium font-mono ${cls}`}
    >
      {pct}%
    </span>
  );
}

function DemoBtn({ icon, label }: { icon: string; label: string }) {
  return (
    <button
      type="button"
      disabled
      title="В разработке"
      className="inline-flex items-center gap-2 px-3 py-2 rounded-md text-sm bg-white border border-slate-200 text-slate-500 cursor-not-allowed"
    >
      <span aria-hidden>{icon}</span>
      <span>{label}</span>
    </button>
  );
}
