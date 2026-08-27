import { createContext, ReactNode, useContext, useState } from "react";
import { UploadResponse } from "./api/client";

interface UploadState {
  uploaded: UploadResponse | null;
  setUploaded: (v: UploadResponse | null) => void;
  busy: boolean;
  setBusy: (v: boolean) => void;
  error: string | null;
  setError: (v: string | null) => void;
}

const UploadStateContext = createContext<UploadState | null>(null);

// Held at the App level (which never unmounts across client-side route changes) so
// an in-progress or just-finished upload survives navigating to another page and
// back - unlike page-local useState, which gets torn down on unmount and made it
// look like switching tabs "interrupted" the upload even when it had actually
// completed successfully server-side.
export function UploadStateProvider({ children }: { children: ReactNode }) {
  const [uploaded, setUploaded] = useState<UploadResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  return (
    <UploadStateContext.Provider value={{ uploaded, setUploaded, busy, setBusy, error, setError }}>
      {children}
    </UploadStateContext.Provider>
  );
}

export function useUploadState(): UploadState {
  const ctx = useContext(UploadStateContext);
  if (!ctx) throw new Error("useUploadState must be used within UploadStateProvider");
  return ctx;
}
