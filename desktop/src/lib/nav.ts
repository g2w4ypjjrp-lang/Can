import { createContext, useContext } from "react";

/** Sayfalar arası geçiş (ör. "Başlarken" kartından Ayarlar'a). App sağlar. */
export const NavContext = createContext<(page: string) => void>(() => undefined);

export function useNavigate(): (page: string) => void {
  return useContext(NavContext);
}
