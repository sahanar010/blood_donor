import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type DonorMe, type DonorReq } from "../api";
import Shell from "../Shell";

export default function Donor() {
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["d-me"], queryFn: () => api<DonorMe>("/donor/me") });
  const reqs = useQuery({ queryKey: ["d-reqs"], queryFn: () => api<DonorReq[]>("/donor/requests") });
  const done = () => qc.invalidateQueries();
  const setStatus = useMutation({ mutationFn: (s: string) => api("/donor/me", "PATCH", { availability_status: s }), onSuccess: done });
  const respond = useMutation({
    mutationFn: (p: { id: number; accepted: boolean }) => api(`/donor/requests/${p.id}/respond`, "POST", { accepted: p.accepted }),
    onSuccess: done,
  });
  const d = me.data;
  const error = (setStatus.error ?? respond.error) as Error | null;

  return (
    <Shell title={d ? `Hello, ${d.name.split(" ")[0]}` : "Donor"}>
      {d && (
        <div className="mb-4 flex flex-wrap items-center gap-x-6 gap-y-2 rounded border border-line bg-white p-3 text-sm">
          <span>Blood group <b>{d.blood_group}</b></span>
          <span>{d.donation_count} donation{d.donation_count === 1 ? "" : "s"}{d.last_donation_date ? `, last on ${d.last_donation_date}` : ""}</span>
          <label className="flex items-center gap-2">Availability
            <select className="field w-auto" value={d.availability_status} onChange={(e) => setStatus.mutate(e.target.value)}>
              <option value="AVAILABLE">Available</option><option value="BUSY">Busy</option><option value="OFFLINE">Offline</option>
            </select>
          </label>
          {!d.verified && <span className="text-amber-800">Not verified yet. Hospitals can't match you until an admin verifies you.</span>}
        </div>
      )}
      {error && <p className="mb-3 rounded border border-red-300 bg-red-50 p-2 text-sm text-blood" role="alert">{error.message}</p>}

      <h2 className="mb-2 font-medium">Blood requests for you</h2>
      {!reqs.data?.length && <p className="text-sm text-ink/60">No requests right now. New ones appear here instantly.</p>}
      <ul className="space-y-2">
        {reqs.data?.map((r) => (
          <li key={r.match_id} className="rounded border border-line bg-white p-3">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="font-medium">
                  {r.blood_group} needed, {r.units_required} unit{r.units_required === 1 ? "" : "s"}
                  <span className={`ml-2 rounded px-1.5 py-0.5 text-xs ${r.urgency === "EMERGENCY" ? "bg-blood text-white" : "bg-line"}`}>{r.urgency.toLowerCase()}</span>
                </p>
                <p className="text-sm text-ink/70">{r.hospital_name}, {r.hospital_address}</p>
                <p className="num text-sm text-ink/70">{r.distance_km} km away · needed by {new Date(r.required_time).toLocaleString()}</p>
                {r.notes && <p className="mt-1 text-sm">{r.notes}</p>}
              </div>
              <div className="flex gap-2">
                <button className="btn btn-primary" disabled={respond.isPending} onClick={() => respond.mutate({ id: r.match_id, accepted: true })}>Accept</button>
                <button className="btn" disabled={respond.isPending} onClick={() => respond.mutate({ id: r.match_id, accepted: false })}>Decline</button>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </Shell>
  );
}
