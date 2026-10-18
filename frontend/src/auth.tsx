import { createContext, useContext, useState, type ReactNode } from "react";
import { BASE, stored, type Auth } from "./api";

type Ctx = { auth: Auth | null; login: (email: string, pw: string) => Promise<Auth>; logout: () => void };
const AuthCtx = createContext<Ctx>(null!);
export const useAuth = () => useContext(AuthCtx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [auth, setAuth] = useState<Auth | null>(stored());
  const login = async (email: string, pw: string) => {
    const r = await fetch(BASE + "/auth/login", { method: "POST", body: new URLSearchParams({ username: email, password: pw }) });
    if (!r.ok) throw new Error(r.status === 401 ? "Incorrect email or password" : `Login failed (${r.status})`);
    const j = await r.json();
    const a: Auth = { token: j.access_token, role: j.role };
    localStorage.setItem("bm_auth", JSON.stringify(a));
    setAuth(a);
    return a;
  };
  const logout = () => { localStorage.removeItem("bm_auth"); setAuth(null); };
  return <AuthCtx.Provider value={{ auth, login, logout }}>{children}</AuthCtx.Provider>;
}
