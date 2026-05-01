import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, fmtMoney, shortName } from "../api";
import { TinLink } from "../components/TinLink";
import type { ListCasesResponse } from "../types";
import { KzBadge } from "../components/StateBadge";

export default function CasesPage() {
  const [data, setData] = useState<ListCasesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  useEffect(() => {
    api
      .getListCases(5)
      .then(setData)
      .catch((err) => setErrMsg(String(err)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <div className="text-slate-500">Загрузка кейсов…</div>;
  }
  if (errMsg) {
    return (
      <div className="card border-red-200 bg-red-50 text-red-800">
        <div className="font-semibold">Ошибка:</div>
        <div className="mt-1 text-sm">{errMsg}</div>
        <p className="mt-3 text-sm">
          Скорее всего, граф ещё не посчитан.{" "}
          <Link to="/home" className="text-teal-700 underline">
            Запустите расчёт на главной
          </Link>
          .
        </p>
      </div>
    );
  }
  if (!data) return null;

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl font-bold text-slate-900">
          Меню кейсов для демо
        </h1>
        <p className="mt-2 text-slate-600 max-w-3xl">
          Четыре типа компаний, на примере которых хорошо видны разные стороны
          экономики страны: точки входа импорта, импортозависимые
          посредники, по-настоящему отечественные производители и компании со
          встречной торговлей. Кликните на БИН, чтобы открыть полный профиль
          и увидеть конкретные цепочки.
        </p>
      </header>

      <Section
        title="① Импортёры — точки входа импорта в экономику"
        accent="amber"
        description={{
          what: "Зарубежные компании (нерезиденты РК), которые в этом периоде продавали свои товары и услуги казахстанским предприятиям. Это — те «двери», через которые импорт физически входит в экономику страны.",
          why: "Они задают стартовую долю импорта во всех цепочках. Когда казахстанская компания у них что-то покупает, она «вносит» эту импортную долю в свою продукцию — а дальше она расходится по всем её клиентам.",
          how: "Чем крупнее импортёр и чем больше у него казахстанских клиентов, тем шире его экономическое влияние. Если задача — снизить долю импорта в конкретной отрасли, эти компании первые в списке: либо договариваться о локализации производства, либо искать им казахстанских аналогов.",
        }}
      >
        {data.importers.length === 0 ? (
          <Empty>(в этом периоде нет нерезидентов с продажами)</Empty>
        ) : (
          <Table
            head={["BIN", "Название", "Продажи", "Покупателей"]}
            rows={data.importers.map((r) => [
              <TinLink tin={r.tin} key="tin" />,
              shortName(r.name, 40),
              fmtMoney(r.sales),
              r.buyers_count,
            ])}
          />
        )}
      </Section>

      <Section
        title="② Зависимые от импорта — отечественные «по форме», импортные «по сути»"
        accent="red"
        description={{
          what: "Казахстанские компании, у которых больше 30% стоимости закупок в итоге оказалось импортной. Формально это отечественные предприятия — но их продукция держится на ввезённых из-за рубежа материалах и услугах.",
          why: "Главный сегмент для политики импортозамещения и проверки добросовестности. Компания может декларировать в тендерах высокий процент казахстанского содержания, но если её собственные поставки опираются на импорт — реальный КС у неё ниже декларируемого.",
          how: "Откройте профиль компании, чтобы увидеть, через каких поставщиков именно к ней приходит импорт. Часто это один-два ключевых контрагента — их замена на казахстанские аналоги сразу повышает реальный КС всей цепочки.",
        }}
      >
        {data.dependents.length === 0 ? (
          <Empty>(нет таких — все цепочки чистые или короткие)</Empty>
        ) : (
          <Table
            head={["BIN", "Название", "Продажи", "kz"]}
            rows={data.dependents.map((r) => [
              <TinLink tin={r.tin} key="tin" />,
              shortName(r.name, 40),
              fmtMoney(r.sales),
              <KzBadge kz={r.kz} key="kz" />,
            ])}
          />
        )}
      </Section>

      <Section
        title="③ Чистые отечественные — потенциальные «якоря» для импортозамещения"
        accent="emerald"
        description={{
          what: "Крупные казахстанские компании, вся видимая цепочка поставщиков которых состоит только из других казахстанских компаний. Импорта в их закупках практически не обнаруживается.",
          why: "Это позитивная часть экономики и естественные «якоря» для импортозамещения. Именно к таким компаниям имеет смысл подвязывать импортозависимых конкурентов из второго раздела как к локальной альтернативе их зарубежным поставщикам.",
          how: "Важная оговорка: «КС ≈ 100%» означает «в сделках, оформленных через электронные счета-фактуры, импорт не обнаружен». Если компания закупает что-то напрямую за рубежом без выписки ЭСФ или платит за услуги через зарубежные платёжные системы, это в нашу картину не попадает. Поэтому «полностью отечественное производство» — всегда вопрос дополнительной проверки в каждом конкретном случае.",
        }}
      >
        {data.clean.length === 0 ? (
          <Empty>(нет таких в этом периоде)</Empty>
        ) : (
          <Table
            head={["BIN", "Название", "Продажи", "kz"]}
            rows={data.clean.map((r) => [
              <TinLink tin={r.tin} key="tin" />,
              shortName(r.name, 40),
              fmtMoney(r.sales),
              <KzBadge kz={r.kz} key="kz" />,
            ])}
          />
        )}
      </Section>

      <Section
        title="④ Встречная торговля — компании, продающие друг другу"
        accent="violet"
        description={{
          what: "Группы компаний, в которых деньги ходят по кругу: A продаёт B, B продаёт C, а C снова продаёт A. То есть каждая компания одновременно и поставщик, и покупатель внутри одной и той же группы.",
          why: "В таких группах казахстанское содержание у всех участников одинаковое — отдельно «вклад» каждого выделить невозможно: их экономики переплетены. Если в группе появляется хотя бы один импортёр — он автоматически снижает КС всем остальным; и наоборот, если все участники работают на казахстанском материале — индекс высокий у всей группы.",
          how: "На практике встречная торговля бывает двух природ. Первая — естественная: компании одного холдинга обмениваются услугами и закупают друг у друга, это норма для группы предприятий. Вторая — искусственная: импорт умышленно «прокручивается» через несколько компаний, чтобы при выходе из круга он выглядел как казахстанская продукция. Такие схемы — повод для проверки. Чтобы понять, к какому типу относится конкретный случай — откройте профили участников и посмотрите, есть ли среди их внешних поставщиков нерезиденты.",
        }}
      >
        {data.cycles.length === 0 ? (
          <Empty>(циклов в графе не найдено)</Empty>
        ) : (
          <div className="space-y-4">
            {data.cycles.map((cycle, idx) => (
              <div key={idx} className="rounded-md border border-slate-200 p-4">
                <div className="font-semibold text-slate-700 mb-2">
                  Цикл #{idx + 1} — {cycle.size} участников
                </div>
                <div className="space-y-1">
                  {cycle.members.slice(0, 5).map((m) => (
                    <div
                      key={m.tin}
                      className="flex items-center gap-3 text-sm"
                    >
                      <TinLink tin={m.tin} />
                      <span className="text-slate-700">
                        {shortName(m.name, 40)}
                      </span>
                      <span className="text-slate-500">
                        {fmtMoney(m.sales)}
                      </span>
                      <KzBadge kz={m.kz} />
                    </div>
                  ))}
                  {cycle.members.length > 5 && (
                    <div className="text-xs text-slate-500">
                      … и ещё {cycle.members.length - 5}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}

type SectionDescription = {
  /** Что это за категория (определение). */
  what: string;
  /** Зачем смотреть на эти компании, какую сторону экономики они показывают. */
  why: string;
  /** Как трактовать результат, на что обратить внимание. */
  how: string;
};

function Section({
  title,
  accent,
  description,
  children,
}: {
  title: string;
  accent: "amber" | "red" | "emerald" | "violet";
  description?: SectionDescription;
  children: React.ReactNode;
}) {
  const accentBorder: Record<typeof accent, string> = {
    amber: "border-l-amber-400",
    red: "border-l-red-400",
    emerald: "border-l-emerald-400",
    violet: "border-l-violet-400",
  };
  return (
    <section className={`card border-l-4 ${accentBorder[accent]} pl-5`}>
      <h2 className="font-semibold text-slate-900 mb-3">{title}</h2>
      {description && (
        <div className="mb-4 rounded-md bg-slate-50 border border-slate-200 px-4 py-3 text-sm space-y-2.5">
          <DescRow label="Что это" text={description.what} />
          <DescRow label="Зачем смотреть" text={description.why} />
          <DescRow label="Как трактовать" text={description.how} />
        </div>
      )}
      {children}
    </section>
  );
}

function DescRow({ label, text }: { label: string; text: string }) {
  return (
    <div className="grid grid-cols-[140px,1fr] gap-3 items-baseline">
      <div className="text-xs uppercase tracking-wide text-slate-500 font-semibold">
        {label}
      </div>
      <div className="text-slate-700 leading-relaxed">{text}</div>
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="text-sm text-slate-500 italic">{children}</div>;
}

function Table({
  head,
  rows,
}: {
  head: React.ReactNode[];
  rows: React.ReactNode[][];
}) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-xs uppercase tracking-wide text-slate-500 border-b border-slate-200">
          {head.map((h, i) => (
            <th key={i} className="py-2 pr-4 font-medium">
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, i) => (
          <tr
            key={i}
            className="border-b border-slate-100 last:border-0 hover:bg-slate-50"
          >
            {row.map((cell, j) => (
              <td key={j} className="py-2 pr-4">
                {cell}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
