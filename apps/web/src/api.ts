import type {
  AggregateResponse,
  CompanyProfileResponse,
  DistributionResponse,
  ListCasesResponse,
  StateResponse,
  TopImporterRow,
} from "./types";

const API_BASE = import.meta.env.VITE_API_URL ?? "";

/** Дольше, чем httpx к Resend на backend (~30 с), иначе обрыв на «Отправка…». */
export const AUTH_FETCH_TIMEOUT_MS = 65_000;

function isTimeoutLike(error: unknown): boolean {
  if (error instanceof DOMException) {
    return error.name === "AbortError" || error.name === "TimeoutError";
  }
  if (error instanceof Error) {
    if (error.name === "TimeoutError") return true;
    if (/timed out/i.test(error.message)) return true;
  }
  return false;
}

export function networkErrorMessage(error: unknown): string {
  if (error instanceof TypeError) {
    return "Не удалось связаться с сервером. Убедитесь, что контейнер backend запущен и пересобран.";
  }
  if (isTimeoutLike(error)) {
    return (
      "Превышено время ожидания. Запрос к почте может занимать до минуты — попробуйте ещё раз. " +
      "Если так и не доходит, проверьте docker compose logs backend и RESEND_* в .env."
    );
  }
  return String(error);
}

/** Разбор `detail` из FastAPI/Pydantic: строка или массив `{ msg, loc, ... }`. */
export function formatApiDetail(detail: unknown): string {
  if (detail == null || detail === "") return "";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (item && typeof item === "object" && "msg" in item) {
          return String((item as { msg: unknown }).msg);
        }
        return null;
      })
      .filter((x): x is string => Boolean(x));
    if (parts.length > 0) return parts.join(" ");
  }
  try {
    return JSON.stringify(detail);
  } catch {
    return String(detail);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    ...init,
  });
  if (!res.ok) {
    let detail = "";
    try {
      const body = await res.json();
      detail = formatApiDetail(body?.detail) || JSON.stringify(body);
    } catch {
      detail = await res.text();
    }
    throw new Error(`HTTP ${res.status}: ${detail || res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  getState: () => request<StateResponse>("/api/state"),

  recompute: (days: number, force = false) =>
    request<StateResponse>("/api/recompute", {
      method: "POST",
      body: JSON.stringify({ days, force }),
    }),

  getAggregate: () => request<AggregateResponse>("/api/aggregate"),
  getDistribution: () => request<DistributionResponse>("/api/distribution"),
  getTopImporters: (n = 10) => request<TopImporterRow[]>(`/api/top-importers?n=${n}`),
  getListCases: (n = 5) => request<ListCasesResponse>(`/api/list-cases?n=${n}`),
  getCompany: (bin: string) =>
    request<CompanyProfileResponse>(`/api/company/${encodeURIComponent(bin)}`),
};

// ---------------------------------------------------------------- formatters

export function fmtMoney(x: number | null | undefined): string {
  if (x == null || Number.isNaN(x)) return "—";
  const sign = x < 0 ? "-" : "";
  const a = Math.abs(x);
  if (a >= 1e9) return `${sign}${(a / 1e9).toFixed(2).replace(".", ",")} млрд ₸`;
  if (a >= 1e6) return `${sign}${(a / 1e6).toFixed(2).replace(".", ",")} млн ₸`;
  if (a >= 1e3) return `${sign}${(a / 1e3).toFixed(0)} тыс ₸`;
  return `${sign}${a.toFixed(0)} ₸`;
}

export function fmtPct(x: number | null | undefined, fractionDigits = 2): string {
  if (x == null || Number.isNaN(x)) return "—";
  return `${x.toFixed(fractionDigits)}%`;
}

export function fmtNum(x: number | null | undefined): string {
  if (x == null || Number.isNaN(x)) return "—";
  return x.toLocaleString("ru-RU");
}

export function shortName(name: string | null | undefined, max = 35): string {
  if (!name) return "(без имени)";
  if (name.length <= max) return name;
  return name.slice(0, max - 1) + "…";
}

export function roleLabel(role: CompanyProfileResponse["card"]["role"]): string {
  switch (role) {
    case "non_resident_importer":
      return "нерезидент-импортёр";
    case "source":
      return "источник (нет поставщиков в графе)";
    case "sink":
      return "конечный потребитель";
    case "intermediary":
      return "посредник";
    default:
      return role;
  }
}
