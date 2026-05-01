import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { CompanyPreviewModal } from "../components/CompanyPreviewModal";

export type TinPreviewContextValue = {
  openTinPreview: (tin: string) => void;
  closeTinPreview: () => void;
};

export const TinPreviewContext = createContext<TinPreviewContextValue | null>(
  null,
);

export function useTinPreviewOptional() {
  return useContext(TinPreviewContext);
}

export function TinPreviewProvider({ children }: { children: ReactNode }) {
  const [tin, setTin] = useState<string | null>(null);

  const openTinPreview = useCallback((raw: string) => {
    const t = raw.trim();
    setTin(t || null);
  }, []);

  const closeTinPreview = useCallback(() => setTin(null), []);

  const value = useMemo(
    () => ({ openTinPreview, closeTinPreview }),
    [openTinPreview, closeTinPreview],
  );

  return (
    <TinPreviewContext.Provider value={value}>
      {children}
      {tin ? (
        <CompanyPreviewModal tin={tin} onClose={closeTinPreview} />
      ) : null}
    </TinPreviewContext.Provider>
  );
}
