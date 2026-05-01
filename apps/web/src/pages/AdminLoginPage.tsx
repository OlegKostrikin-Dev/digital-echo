import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AUTH_FETCH_TIMEOUT_MS, formatApiDetail, networkErrorMessage } from "../api";
import { useAuth } from "../context/AuthContext";

const API_BASE = import.meta.env.VITE_API_URL ?? "";

export default function AdminLoginPage() {
  const [step, setStep] = useState<"email" | "code">("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const { refresh } = useAuth();
  const navigate = useNavigate();

  async function onRequestOtp(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    setMsg(null);
    setPending(true);
    try {
      const r = await fetch(`${API_BASE}/api/auth/admin/request-otp`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim() }),
        signal: AbortSignal.timeout(AUTH_FETCH_TIMEOUT_MS),
      });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) {
        setErr(formatApiDetail(b.detail) || r.statusText);
        return;
      }
      setMsg(
        String(
          b.message ??
            "Если адрес есть среди администраторов, проверьте почту (и «Спам»), затем введите код ниже.",
        ),
      );
      setStep("code");
    } catch (x) {
      setErr(networkErrorMessage(x));
    } finally {
      setPending(false);
    }
  }

  async function onVerify(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    setPending(true);
    try {
      const r = await fetch(`${API_BASE}/api/auth/admin/verify-otp`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim(), code: code.trim() }),
        signal: AbortSignal.timeout(AUTH_FETCH_TIMEOUT_MS),
      });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) {
        setErr(formatApiDetail(b.detail) || r.statusText);
        return;
      }
      await refresh();
      navigate("/admin/invites", { replace: true });
    } catch (x) {
      setErr(networkErrorMessage(x));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="min-h-screen flex flex-col bg-slate-50">
      <header className="border-b bg-white px-6 py-4 flex justify-between items-center">
        <Link to="/" className="text-sm text-teal-700 hover:underline">
          ← На главную
        </Link>
        <Link to="/access" className="text-sm text-slate-600 hover:underline">
          Вход гостя
        </Link>
      </header>
      <div className="flex-1 flex items-center justify-center p-6">
        <div className="w-full max-w-md card space-y-4">
          <h1 className="text-xl font-semibold text-slate-900">
            Вход администратора
          </h1>
          {step === "email" ? (
            <form onSubmit={onRequestOtp} className="space-y-3">
              <p className="text-sm text-slate-600">
                На ваш админский email будет отправлен одноразовый код.
              </p>
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">
                  Email
                </label>
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                  autoComplete="email"
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
                {pending ? "Отправка…" : "Получить код"}
              </button>
            </form>
          ) : (
            <form onSubmit={onVerify} className="space-y-3">
              {msg && (
                <div className="text-sm text-emerald-800 bg-emerald-50 border border-emerald-200 rounded-md p-2">
                  {msg}
                </div>
              )}
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">
                  Код из письма
                </label>
                <input
                  type="text"
                  required
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm font-mono"
                  autoComplete="one-time-code"
                />
              </div>
              {err && (
                <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-md p-2">
                  {err}
                </div>
              )}
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setStep("email");
                    setCode("");
                    setErr(null);
                  }}
                  className="flex-1 border border-slate-300 rounded-md py-2 text-sm"
                >
                  Назад
                </button>
                <button
                  type="submit"
                  disabled={pending}
                  className="flex-1 btn-primary disabled:opacity-50"
                >
                  {pending ? "Вход…" : "Войти"}
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
