export const BASE: string = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export type Auth = { token: string; role: "DONOR" | "HOSPITAL" | "ADMIN" };
export const stored = (): Auth | null => {
  try { return JSON.parse(localStorage.getItem("bm_auth") || "null"); } catch { return null; }
};

export async function api<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const a = stored();
  const r = await fetch(BASE + path, {
    method,
    headers: { "Content-Type": "application/json", ...(a ? { Authorization: `Bearer ${a.token}` } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (r.status === 401 && a) { localStorage.removeItem("bm_auth"); location.href = "/login"; }
  const data = await r.json().catch(() => null);
  if (!r.ok) {
    const d = data?.detail;
    throw new Error(Array.isArray(d) ? d.map((x: { msg: string }) => x.msg).join("; ") : d ?? `Request failed (${r.status})`);
  }
  return data as T;
}

export type Req = { id: number; blood_group: string; units_required: number; units_fulfilled: number;
  urgency: string; required_time: string; max_distance_km: number; status: string };
export type Match = { match_id: number; donor_ref: string; distance_km: number; score: number; reasons: string[];
  rating_avg: number | null; status: string; donor_online: boolean; donor_name: string | null; donor_phone: string | null };
export type HospitalMe = { name: string; address: string; latitude: number; longitude: number; verified: boolean };
export type DonorMe = { ref: string; name: string; blood_group: string; availability_status: string;
  verified: boolean; last_donation_date: string | null; donation_count: number };
export type DonorReq = { match_id: number; hospital_name: string; hospital_address: string; blood_group: string;
  units_required: number; urgency: string; required_time: string; distance_km: number; notes: string | null };
