import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

const DOCS_BASE = import.meta.env.VITE_DOCS_URL || "http://localhost:8080";
// Для нетехнической аудитории ведём сразу на «простыми словами»,
// а не на корень документации с тех. деталями.
const DOCS_URL = `${DOCS_BASE}/executive-summary/`;

const navLinkBase =
  "px-3 py-1.5 rounded-md text-sm font-medium transition-colors";
const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  isActive
    ? `${navLinkBase} bg-teal-600 text-white`
    : `${navLinkBase} text-slate-700 hover:bg-slate-200`;

export default function Layout() {
  const { logout, user } = useAuth();
  const navigate = useNavigate();

  async function onLogout() {
    await logout();
    navigate("/", { replace: true });
  }

  return (
    <div className="min-h-screen flex flex-col">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/80 backdrop-blur">
        <div className="mx-auto max-w-6xl px-6 py-3 flex items-center gap-6">
          <Link to="/home" className="font-semibold text-slate-900 tracking-tight">
            digital-echo-core
          </Link>
          <nav className="flex gap-1">
            <NavLink to="/home" end className={navLinkClass}>
              Главная
            </NavLink>
            <NavLink to="/cases" className={navLinkClass}>
              Кейсы
            </NavLink>
            <NavLink to="/search" className={navLinkClass}>
              Поиск по BIN
            </NavLink>
          </nav>
          <div className="ml-auto flex items-center gap-3">
            {user?.role === "admin" && (
              <Link
                to="/admin/invites"
                className="text-sm text-slate-600 hover:text-slate-900"
              >
                Инвайты
              </Link>
            )}
            <span className="text-xs text-slate-500 max-w-[160px] truncate hidden sm:inline">
              {user?.email}
            </span>
            <button
              type="button"
              onClick={onLogout}
              className="text-sm text-slate-600 hover:text-slate-900 underline-offset-2 hover:underline"
            >
              Выйти
            </button>
            <a
              href={DOCS_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-ghost text-sm"
            >
              Документация ↗
            </a>
          </div>
        </div>
      </header>
      <main className="flex-1">
        <div className="mx-auto max-w-6xl px-6 py-8">
          <Outlet />
        </div>
      </main>
      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto max-w-6xl px-6 py-3 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
          <div>
            Прототип. Источники: корпоративная БД электронных
            счетов-фактур (MySQL) и справочник налогоплательщиков
            (VoltDB). Не для production-выводов.
          </div>
          <div className="text-slate-600">
            Разработка решения —{" "}
            <span className="font-medium text-slate-700">
              ТОО «Open Systems Development»
            </span>
          </div>
        </div>
      </footer>
    </div>
  );
}
