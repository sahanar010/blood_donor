import type { ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { useAuth } from "./auth";
import { useRealtime } from "./useRealtime";

export default function Shell({ title, children }: { title: string; children: ReactNode }) {
  const qc = useQueryClient();
  const { logout } = useAuth();
  const nav = useNavigate();
  const live = useRealtime(() => qc.invalidateQueries());
  return (
    <div className="mx-auto max-w-6xl p-4">
      <header className="mb-4 flex items-center justify-between border-b border-line pb-3">
        <h1 className="text-lg font-semibold">{title}</h1>
        <div className="flex items-center gap-3 text-sm">
          <span className="flex items-center gap-1.5" role="status">
            <span className={`h-2 w-2 rounded-full ${live ? "bg-green-600" : "bg-amber-500"}`} />
            {live ? "Live updates on" : "Reconnecting…"}
          </span>
          <button className="btn" onClick={() => { logout(); nav("/login"); }}>Log out</button>
        </div>
      </header>
      {children}
    </div>
  );
}
