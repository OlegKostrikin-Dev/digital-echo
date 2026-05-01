// Зеркало backend Pydantic-схем

export type Status = "idle" | "computing" | "ready" | "error";

export interface StateMeta {
  date_from?: string;
  date_to?: string;
  days?: number;
  raw_edges?: number;
  edges_after_filter?: number;
  edges_dropped?: number;
  nodes?: number;
  voltdb?: {
    voltdb_available: boolean;
    resolved: number;
    non_resident: number;
    missing: number;
    unknown_state: number;
  };
  compute?: {
    iterations: number;
    converged: boolean;
    delta_max: number;
    fixed_total: number;
    fixed_non_resident: number;
    fixed_resident_source: number;
    free_nodes: number;
  };
  empty?: boolean;
}

export interface StateResponse {
  status: Status;
  days?: number;
  started_at?: string;
  finished_at?: string;
  duration_seconds?: number;
  error?: string;
  meta?: StateMeta;
  readonly?: boolean;
  snapshot_saved_at?: string;
}

export interface AggregateResponse {
  sellers_count: number;
  total_sales: number;
  import_value: number;
  domestic_value: number;
  import_share_pct: number;
  domestic_share_pct: number;
}

export interface HistogramBucket {
  label: string;
  count: number;
  pct: number;
}

export interface DistributionResponse {
  total: number;
  histogram: HistogramBucket[];
  summary: {
    mean: number;
    std: number;
    min: number;
    p25: number;
    p50: number;
    p75: number;
    max: number;
  };
}

export interface TopImporterRow {
  tin: string;
  name: string | null;
  is_non_resident: boolean;
  kz: number;
  sales: number;
  import_value: number;
}

export interface ImporterCase {
  tin: string;
  name: string | null;
  sales: number;
  buyers_count: number;
}

export interface DependentCase {
  tin: string;
  name: string | null;
  sales: number;
  kz: number;
}

export interface CleanCase {
  tin: string;
  name: string | null;
  sales: number;
  kz: number;
}

export interface CycleMember {
  tin: string;
  name: string | null;
  kz: number;
  sales: number;
}

export interface CycleCase {
  size: number;
  members: CycleMember[];
}

export interface ListCasesResponse {
  importers: ImporterCase[];
  dependents: DependentCase[];
  clean: CleanCase[];
  cycles: CycleCase[];
}

export interface CompanyCard {
  tin: string;
  name: string | null;
  is_non_resident: boolean | null;
  in_degree: number;
  out_degree: number;
  role: "non_resident_importer" | "source" | "sink" | "intermediary";
  purchases: number;
  sales: number;
  kz: number;
  import_value_in_sales: number;
}

export interface SupplierRow {
  tin: string;
  name: string | null;
  is_non_resident: boolean;
  weight: number;
  share: number;
  kz: number;
}

export interface BackwardLayer {
  level: number;
  size: number;
  avg_kz: number;
  non_resident_count: number;
}

export interface BackwardView {
  applicable: boolean;
  reason?: string;
  suppliers: SupplierRow[];
  suppliers_total: number;
  direct_import: {
    value: number;
    share: number;
    non_resident_suppliers_count: number;
  } | null;
  layers: BackwardLayer[];
  cone_size: number;
  cone_share: number;
}

export interface CustomerRow {
  tin: string;
  name: string | null;
  weight: number;
  share_in_buyer: number;
  kz: number;
}

export interface ForwardLayer {
  level: number;
  size: number;
  layer_sales: number;
  avg_kz: number;
  end_consumers: number;
}

export interface ForwardView {
  applicable: boolean;
  reason?: string;
  customers: CustomerRow[];
  customers_total: number;
  layers: ForwardLayer[];
  cone_size: number;
  cone_share: number;
}

export interface CompanyProfileResponse {
  card: CompanyCard;
  backward: BackwardView;
  forward: ForwardView;
}
