import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type HospitalMe, type Match, type Req } from "../api";
import MatchMap from "../MatchMap";
import Shell from "../Shell";

const GROUPS = ["O+", "O-", "A+", "A-", "B+", "B-", "AB+", "AB-"];
const pad = (n: number) => String(n).padStart(2, "0");
const inTwoHours = () => {
  const d = new Date(Date.now() + 2 * 36e5);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};
const chip: Record<string, string> = {
  SUGGESTED: "bg-line text-ink", REQUESTED: "bg-amber-100 text-amber-900", ACCEPTED: "bg-green-100 text-green-900",
  DECLINED: "bg-red-100 text-red-900", COMPLETED: "bg-sea text-white",
};
const ringColor: Record<string, string> = { ACCEPTED: "#15803d", COMPLETED: "#2B6E73", REQUESTED: "#d97706", SUGGESTED: "#64748b" };

export default function Hospital() {
  const qc = useQueryClient();
  const [sel, setSel] = useState<number | null>(null);
  const [f, setF] = useState({ blood_group: "O+", units_required: 1, urgency: "NORMAL", max_distance_km: 15, required_time: inTwoHours() });

  const me = useQuery({ queryKey: ["h-me"], queryFn: () => api<HospitalMe>("/hospital/me") });
  const verified = !!me.data?.verified;
  const reqs = useQuery({ queryKey: ["h-reqs"], queryFn: () => api<Req[]>("/hospital/requests"), enabled: verified });
  const cur = reqs.data?.find((r) => r.id === sel) ?? reqs.data?.[0];
  const matches = useQuery({ queryKey: ["h-matches", cur?.id], queryFn: () => api<Match[]>(`/hospital/requests/${cur!.id}/matches`), enabled: !!cur });

  const create = useMutation({
    mutationFn: () => api<Req>("/hospital/requests", "POST", f),
    onSuccess: (r) => { setSel(r.id); qc.invalidateQueries(); },
  });
  const act = useMutation({
    mutationFn: (p: { path: string; body?: unknown }) => api("/hospital" + p.path, "POST", p.body ?? {}),
    onSuccess: () => qc.invalidateQueries(),
  });
  const error = (create.error ?? act.error) as Error | null;
  const list = matches.data ?? [];
  const open = cur?.status === "OPEN";
  const submit = (e: FormEvent) => { e.preventDefault(); create.mutate(); };

  return (
    <Shell title={me.data?.name ?? "Hospital"}>
      {me.data && !verified && (
        <p className="rounded border border-amber-300 bg-amber-50 p-3 text-sm">
          Waiting for admin verification. You can create blood requests once your hospital is verified.
        </p>
      )}
      {verified && (
        <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
          <aside className="space-y-4">
            <form onSubmit={submit} className="space-y-2 rounded border border-line bg-white p-3">
              <h2 className="font-medium">New blood request</h2>
              <div className="grid grid-cols-2 gap-2">
                <label className="text-sm">Blood group
                  <select className="field" value={f.blood_group} onChange={(e) => setF({ ...f, blood_group: e.target.value })}>
                    {GROUPS.map((g) => <option key={g}>{g}</option>)}
                  </select></label>
                <label className="text-sm">Units
                  <input className="field" type="number" min={1} max={10} value={f.units_required} onChange={(e) => setF({ ...f, units_required: +e.target.value })} /></label>
                <label className="text-sm">Urgency
                  <select className="field" value={f.urgency} onChange={(e) => setF({ ...f, urgency: e.target.value })}>
                    <option>NORMAL</option><option>URGENT</option><option>EMERGENCY</option>
                  </select></label>
                <label className="text-sm">Max distance (km)
                  <input className="field" type="number" min={1} max={200} value={f.max_distance_km} onChange={(e) => setF({ ...f, max_distance_km: +e.target.value })} /></label>
              </div>
              <label className="block text-sm">Needed by
                <input className="field" type="datetime-local" required value={f.required_time} onChange={(e) => setF({ ...f, required_time: e.target.value })} /></label>
              <button className="btn btn-primary w-full" disabled={create.isPending}>Create request</button>
            </form>

            <div className="rounded border border-line bg-white p-3">
              <h2 className="mb-2 font-medium">Your requests</h2>
              {!reqs.data?.length && <p className="text-sm text-ink/60">No requests yet. Create one above.</p>}
              <ul className="space-y-1">
                {reqs.data?.map((r) => (
                  <li key={r.id}>
                    <button onClick={() => setSel(r.id)} className={`w-full rounded border px-2 py-1.5 text-left text-sm ${r.id === cur?.id ? "border-sea bg-paper" : "border-line"}`}>
                      <b>{r.blood_group}</b> × {r.units_required} · {r.urgency.toLowerCase()}
                      <span className="block text-xs text-ink/60">#{r.id} · {r.status.toLowerCase()} · {r.units_fulfilled}/{r.units_required} done</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          </aside>

          <section className="space-y-4">
            {error && <p className="rounded border border-red-300 bg-red-50 p-2 text-sm text-blood" role="alert">{error.message}</p>}
            {!cur ? <p className="text-ink/60">Create a request to find donors.</p> : (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="mr-2 text-lg font-medium">Request #{cur.id}: {cur.blood_group} × {cur.units_required}</h2>
                  <button className="btn" disabled={!open || act.isPending} onClick={() => act.mutate({ path: `/requests/${cur.id}/find-donors?top_n=3` })}>Find donors</button>
                  <button className="btn btn-primary" disabled={!open || act.isPending || !list.some((m) => m.status === "SUGGESTED")}
                    onClick={() => act.mutate({ path: `/requests/${cur.id}/send-requests` })}>Send requests</button>
                  <button className="btn" disabled={!open || act.isPending} onClick={() => act.mutate({ path: `/requests/${cur.id}/close`, body: { status: "CANCELLED" } })}>Cancel request</button>
                </div>

                {!list.length && <p className="text-sm text-ink/60">No donors yet. Select Find donors to rank the best matches.</p>}
                <ol className="space-y-2">
                  {list.map((m) => (
                    <li key={m.match_id} className="rounded border border-line bg-white p-3">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="flex items-center gap-2">
                            <span title={m.donor_online ? "Online now" : "Offline"} className={`h-2 w-2 rounded-full ${m.donor_online ? "bg-green-600" : "bg-line"}`} />
                            <b>{m.donor_name ?? m.donor_ref}</b>
                            <span className={`rounded px-1.5 py-0.5 text-xs ${chip[m.status]}`}>{m.status.toLowerCase()}</span>
                          </div>
                          <p className="mt-1 text-sm text-ink/70">{m.reasons.join(" • ")}</p>
                          {m.donor_phone && <p className="mt-1 text-sm">Phone: <a className="underline" href={`tel:${m.donor_phone}`}>{m.donor_phone}</a></p>}
                        </div>
                        <div className="text-right"><div className="num text-2xl font-semibold">{m.score}</div><div className="text-xs text-ink/60">match score</div></div>
                      </div>
                      {m.status === "ACCEPTED" && open && (
                        <button className="btn mt-2" disabled={act.isPending}
                          onClick={() => act.mutate({ path: `/matches/${m.match_id}/record-donation`, body: { verified_volume_ml: 350, experience_rating: 5 } })}>
                          Record donation (350 ml)
                        </button>
                      )}
                    </li>
                  ))}
                </ol>

                {me.data && (
                  <MatchMap center={[me.data.latitude, me.data.longitude]} maxKm={cur.max_distance_km}
                    rings={list.filter((m) => m.status !== "DECLINED").map((m) => ({ label: m.donor_ref, km: m.distance_km, color: ringColor[m.status] ?? "#64748b" }))} />
                )}
              </>
            )}
          </section>
        </div>
      )}
    </Shell>
  );
}
