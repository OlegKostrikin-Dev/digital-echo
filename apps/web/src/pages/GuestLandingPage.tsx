import { Link } from "react-router-dom";

const DOCS_BASE = import.meta.env.VITE_DOCS_URL || "http://localhost:8080";
const DOCS_URL = `${DOCS_BASE}/executive-summary/`;

/**
 * Публичная гостевая страница: только приветствие и кратко о проекте.
 * Данные ЭСФ и аналитика — только после входа по коду.
 */
export default function GuestLandingPage() {
  return (
    <div className="min-h-screen flex flex-col bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-3xl px-6 py-6 flex flex-wrap items-center justify-between gap-3">
          <span className="font-semibold text-slate-900">digital-echo-core</span>
          <div className="flex flex-wrap gap-2 text-sm">
            <Link
              to="/access"
              className="rounded-md bg-teal-600 px-4 py-2 text-white font-medium hover:bg-teal-700"
            >
              Вход по коду доступа
            </Link>
            <Link
              to="/admin/login"
              className="rounded-md border border-slate-300 px-4 py-2 text-slate-700 hover:bg-slate-50"
            >
              Админ
            </Link>
          </div>
        </div>
      </header>
      <main className="flex-1 mx-auto max-w-3xl px-6 py-12 space-y-6">
        <h1 className="text-3xl font-bold text-slate-900 tracking-tight">
          Индекс казахстанского содержания
        </h1>
        <p className="text-slate-700 leading-relaxed">
          Это демонстрационный стенд аналитики по B2B-сделкам из электронных
          счетов-фактур: оценка доли отечественной цепочки поставок и
          прозрачность импортной составляющей. Подробности о целях проекта — в{" "}
          <a
            href={DOCS_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="text-teal-700 underline underline-offset-2 font-medium"
          >
            кратком описании
          </a>
          .
        </p>
        <p className="text-slate-600 text-sm leading-relaxed">
          Доступ к цифрам, кейсам и расчётам открывается по коду из
          письма-приглашения (вводите только код, без email). Код действует ограниченное
          время с момента выдачи. Если письма нет — обратитесь к администратору демо.
        </p>
        <div className="pt-4 border-t border-slate-200 text-xs text-slate-500">
          Разработка решения —{" "}
          <span className="font-medium text-slate-600">
            ТОО «Open Systems Development»
          </span>
        </div>
      </main>
    </div>
  );
}
