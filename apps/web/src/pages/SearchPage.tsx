import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { TinLink } from "../components/TinLink";

export default function SearchPage() {
  const [tin, setTin] = useState("");
  const navigate = useNavigate();

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const v = tin.trim();
    if (!v) return;
    navigate(`/company/${encodeURIComponent(v)}`);
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-slate-900">
          Поиск компании по BIN
        </h1>
        <p className="mt-1 text-slate-600">
          Введите БИН или ИИН — увидите полный профиль с backward- и forward-конусами.
        </p>
      </header>

      <form onSubmit={onSubmit} className="card">
        <label className="block text-sm font-medium text-slate-700 mb-2">
          BIN (БИН / ИИН)
        </label>
        <div className="flex gap-3">
          <input
            type="text"
            value={tin}
            onChange={(e) => setTin(e.target.value)}
            placeholder="например, 180640000680"
            className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm font-mono focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500"
            autoFocus
          />
          <button type="submit" className="btn-primary">
            Открыть профиль
          </button>
        </div>
        <p className="mt-2 text-xs text-slate-500">
          Можно с ведущими нулями или без. Длина 12 символов или меньше — нормализация
          применяется автоматически.
        </p>
      </form>

      <div className="card border-dashed">
        <h3 className="font-medium text-slate-700 mb-2">Подсказки</h3>
        <ul className="text-sm text-slate-600 space-y-1 list-disc pl-5">
          <li>
            <TinLink tin="180640000680" /> — нерезидент-импортёр (Company
            85645214)
          </li>
          <li>
            <TinLink tin="123456789021" /> — ТОО «Асем-2», kz≈0.38, цикл
          </li>
          <li>
            <TinLink tin="240140001872" /> — крупная чистая компания, kz=1.00
          </li>
        </ul>
      </div>
    </div>
  );
}
