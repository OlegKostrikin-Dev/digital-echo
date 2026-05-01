import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AUTH_FETCH_TIMEOUT_MS, formatApiDetail, networkErrorMessage } from "../api";
import { useAuth } from "../context/AuthContext";

const API_BASE = import.meta.env.VITE_API_URL ?? "";

export default function AccessPage() {
  const [code, setCode] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const { refresh } = useAuth();
  const navigate = useNavigate();

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    setPending(true);
    try {
      const r = await fetch(`${API_BASE}/api/auth/guest/verify`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: code.trim() }),
        signal: AbortSignal.timeout(AUTH_FETCH_TIMEOUT_MS),
      });
      if (!r.ok) {
        const b = await r.json().catch(() => ({}));
        setErr(formatApiDetail(b.detail) || r.statusText);
        return;
      }
      await refresh();
      navigate("/home", { replace: true });
    } catch (x) {
      setErr(networkErrorMessage(x));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="min-h-screen flex flex-col bg-slate-50">
      <header className="border-b bg-white px-6 py-4">
        <Link to="/" className="text-sm text-teal-700 hover:underline">
          ← На главную
        </Link>
      </header>
      <div className="flex-1 flex items-center justify-center p-6">
        <div className="w-full max-w-md card space-y-4">
          <h1 className="text-xl font-semibold text-slate-900">Вход по коду доступа</h1>
          <p className="text-sm text-slate-600">
            Введите шестизначный код из письма-приглашения. Одним и тем же кодом можно
            входить повторно, пока не истёк срок, указанный в письме.
          </p>
          <form onSubmit={onSubmit} className="space-y-3">
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">
                Код доступа
              </label>
              <input
                type="text"
                required
                minLength={6}
                maxLength={12}
                inputMode="numeric"
                autoCapitalize="off"
                autoCorrect="off"
                spellCheck={false}
                value={code}
                onChange={(e) => setCode(e.target.value)}
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm font-mono tracking-wide"
                autoComplete="one-time-code"
                placeholder="000000"
              />
            </div>
            {err && (
              <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-md p-2">
                {err}
              </div>
            )}
            <button
              type="submit"
              disabled={pending}
              className="w-full btn-primary disabled:opacity-50"
            >
              {pending ? "Проверка…" : "Войти"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
