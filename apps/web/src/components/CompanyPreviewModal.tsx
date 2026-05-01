import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, fmtMoney, fmtNum, roleLabel, shortName } from "../api";
import type { CompanyProfileResponse } from "../types";
import { Gauge } from "./Gauge";

type Props = {
  tin: string;
  onClose: () => void;
};

export function CompanyPreviewModal({ tin, onClose }: Props) {
  const [profile, setProfile] = useState<CompanyProfileResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErrMsg(null);
    setProfile(null);
    api
      .getCompany(tin)
      .then((p) => {
        if (!cancelled) setProfile(p);
      })
      .catch((e) => {
        if (!cancelled) setErrMsg(String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tin]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose]);

  const { card } = profile ?? {};

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-[1px]"
      role="dialog"
      aria-modal="true"
      aria-labelledby="tin-preview-title"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="w-full max-w-lg rounded-xl border border-slate-200 bg-white shadow-xl shadow-slate-900/10 max-h-[90vh] overflow-y-auto"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-slate-100 px-5 py-4">
          <h2
            id="tin-preview-title"
            className="text-base font-semibold text-slate-900"
          >
            Карточка компании
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
            aria-label="Закрыть"
          >
            ✕
          </button>
        </div>

        <div className="px-5 py-4">
          {loading && (
            <div className="text-sm text-slate-500 py-8 text-center">
              Загрузка…
            </div>
          )}
          {!loading && errMsg && (
            <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
              {errMsg}
            </div>
          )}
          {!loading && !errMsg && card && (
            <div className="space-y-4">
              <div className="flex flex-wrap items-start gap-4">
                <Gauge value={card.kz} caption="индекс КС" size={140} />
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap gap-2 mb-1">
                    <span className="badge bg-slate-100 text-slate-700 text-xs">
                      {roleLabel(card.role)}
                    </span>
                    {card.is_non_resident === false && (
                      <span className="badge bg-emerald-100 text-emerald-800 text-xs">
                        резидент РК
                      </span>
                    )}
                    {card.is_non_resident === true && (
                      <span className="badge bg-amber-100 text-amber-800 text-xs">
                        нерезидент
                      </span>
                    )}
                  </div>
                  <div className="font-semibold text-slate-900 leading-snug">
                    {shortName(card.name, 48)}
                  </div>
                  <div className="mt-0.5 font-mono text-xs text-slate-500">
                    БИН {card.tin}
                  </div>
                </div>
              </div>

              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                <dt className="text-slate-500">Закупки</dt>
                <dd className="font-medium text-right">
                  {fmtMoney(card.purchases)}
                </dd>
                <dt className="text-slate-500">Продажи</dt>
                <dd className="font-medium text-right">
                  {fmtMoney(card.sales)}
                </dd>
                <dt className="text-slate-500">Поставщиков</dt>
                <dd className="text-right">{fmtNum(card.in_degree)}</dd>
                <dt className="text-slate-500">Покупателей</dt>
                <dd className="text-right">{fmtNum(card.out_degree)}</dd>
              </dl>

              <div className="flex flex-wrap gap-2 pt-1">
                <Link
                  to={`/company/${encodeURIComponent(card.tin)}`}
                  className="btn-primary text-sm py-2 px-4"
                  onClick={onClose}
                >
                  Полный профиль
                </Link>
                <button
                  type="button"
                  onClick={onClose}
                  className="text-sm text-slate-600 hover:text-slate-900 px-3 py-2"
                >
                  Закрыть
                </button>
              </div>
              <p className="text-xs text-slate-500">
                Обычный клик открывает это окно. Ctrl/Cmd + клик по БИНу —
                сразу полная страница в новой вкладке.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
