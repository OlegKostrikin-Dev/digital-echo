import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AUTH_FETCH_TIMEOUT_MS, formatApiDetail, networkErrorMessage } from "../api";
import { RequireAdmin } from "../context/AuthContext";

const API_BASE = import.meta.env.VITE_API_URL ?? "";

type InviteRow = {
  id: number;
  guest_email: string;
  expires_at: string;
  created_by: string;
  created_at: string;
  blocked: boolean;
};

function statusCell(r: InviteRow) {
  const exp = new Date(r.expires_at);
  const expired = exp.getTime() < Date.now();
  if (r.blocked) {
    return <span className="text-red-700 font-medium">заблокирован</span>;
  }
  if (expired) {
    return <span className="text-slate-500">истёк</span>;
  }
  return <span className="text-emerald-800">активен</span>;
}

function InvitesBody() {
  const [items, setItems] = useState<InviteRow[]>([]);
  const [email, setEmail] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [rowPending, setRowPending] = useState<number | null>(null);

  async function load() {
    try {
      const r = await fetch(`${API_BASE}/api/auth/admin/invites`, {
        credentials: "include",
        signal: AbortSignal.timeout(AUTH_FETCH_TIMEOUT_MS),
      });
      if (!r.ok) return;
      const d = (await r.json()) as { items?: InviteRow[] };
      setItems(d.items ?? []);
    } catch (x) {
      setErr(networkErrorMessage(x));
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    setOk(null);
    setPending(true);
    try {
      const r = await fetch(`${API_BASE}/api/auth/admin/invites`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ guest_email: email.trim() }),
        signal: AbortSignal.timeout(AUTH_FETCH_TIMEOUT_MS),
      });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) {
        setErr(formatApiDetail(b.detail) || r.statusText);
        return;
      }
      setOk(
        "Код отправлен на почту. Повторная отправка на тот же адрес обновляет срок, код и снимает блокировку.",
      );
      setEmail("");
      await load();
    } catch (x) {
      setErr(networkErrorMessage(x));
    } finally {
      setPending(false);
    }
  }

  async function patchBlocked(id: number, blocked: boolean) {
    setErr(null);
    setRowPending(id);
    try {
      const r = await fetch(`${API_BASE}/api/auth/admin/invites/${id}`, {
        method: "PATCH",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ blocked }),
        signal: AbortSignal.timeout(AUTH_FETCH_TIMEOUT_MS),
      });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) {
        setErr(formatApiDetail(b.detail) || r.statusText);
        return;
      }
      await load();
    } catch (x) {
      setErr(networkErrorMessage(x));
    } finally {
      setRowPending(null);
    }
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b bg-white px-6 py-4 flex flex-wrap gap-3 items-center justify-between">
        <Link to="/home" className="text-sm text-teal-700 hover:underline">
          ← К приложению
        </Link>
        <span className="text-sm font-medium text-slate-700">Админ — инвайты</span>
      </header>
      <div className="mx-auto max-w-5xl px-6 py-8 space-y-8">
        <section className="card space-y-3">
          <h2 className="font-semibold text-slate-900">Новый инвайт</h2>
          <p className="text-sm text-slate-600">
            На один email — одно приглашение. Повторная отправка задаёт новый код и отсчёт{' '}
            <strong>7 дней</strong> с момента отправки. Код не одноразовый: гость может входить
            им многократно, пока срок не истёк и доступ не заблокирован.
          </p>
          <form onSubmit={onSubmit} className="flex flex-wrap gap-2 items-end">
            <div className="flex-1 min-w-[200px]">
              <label className="block text-xs text-slate-600 mb-1">Email гостя</label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
            <button
              type="submit"
              disabled={pending}
              className="btn-primary disabled:opacity-50"
            >
              {pending ? "Отправка…" : "Выслать код"}
            </button>
          </form>
          {err && (
            <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-md p-2">
              {err}
            </div>
          )}
          {ok && (
            <div className="text-sm text-emerald-800 bg-emerald-50 border border-emerald-200 rounded-md p-2">
              {ok}
            </div>
          )}
        </section>

        <section className="card">
          <h2 className="font-semibold text-slate-900 mb-3">Приглашения</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase text-slate-500 border-b">
                  <th className="py-2 pr-2">Email</th>
                  <th className="py-2 pr-2">Истекает</th>
                  <th className="py-2 pr-2">Статус</th>
                  <th className="py-2 pr-2">Кем</th>
                  <th className="py-2 pr-2 text-right">Действия</th>
                </tr>
              </thead>
              <tbody>
                {items.map((r) => (
                  <tr key={r.id} className="border-b border-slate-100">
                    <td className="py-2 pr-2 font-mono text-xs">{r.guest_email}</td>
                    <td className="py-2 pr-2 text-xs text-slate-600">
                      {new Date(r.expires_at).toLocaleString("ru-RU")}
                    </td>
                    <td className="py-2 pr-2">{statusCell(r)}</td>
                    <td className="py-2 pr-2 text-xs">{r.created_by}</td>
                    <td className="py-2 pl-2 text-right whitespace-nowrap">
                      {r.blocked ? (
                        <button
                          type="button"
                          disabled={rowPending === r.id}
                          onClick={() => patchBlocked(r.id, false)}
                          className="text-xs text-teal-700 hover:underline disabled:opacity-50"
                        >
                          Разблокировать
                        </button>
                      ) : (
                        <button
                          type="button"
                          disabled={rowPending === r.id}
                          onClick={() => patchBlocked(r.id, true)}
                          className="text-xs text-red-700 hover:underline disabled:opacity-50"
                        >
                          Заблокировать
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {items.length === 0 && (
              <p className="text-sm text-slate-500 py-4">Пока нет записей.</p>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

export default function AdminInvitesPage() {
  return (
    <RequireAdmin>
      <InvitesBody />
    </RequireAdmin>
  );
}
