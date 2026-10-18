# Blood Donor–Hospital Matching — Phases 1–4 (backend + realtime + React frontend + ML ranking)

FastAPI + PostgreSQL/PostGIS. Hospital creates a request → engine filters and ranks donors →
top 3 with explanations → hospital sends requests → donor accepts/declines → hospital sees the result.
Phase 2 adds live WebSocket updates, so the hospital dashboard changes the instant a donor responds.

## Run it
```bash
docker compose up --build                                  # API + PostGIS
docker compose exec backend python -m scripts.seed --donors 10000   # synthetic data
# open http://localhost:8000/docs  (Swagger UI with an Authorize button)
# open http://localhost:8000/demo  (live two-pane realtime demo, see Phase 2 below)
```
No Docker? Try the engine alone: `cd backend && python3 -m scripts.demo_rank`
Tests (no DB needed): `cd backend && python3 -m unittest discover -s tests -v`

## Demo logins (all synthetic)
| Role | Email | Password |
|---|---|---|
| Admin | admin@demo.local | admin12345 |
| Hospital (verified) | hospital1@demo.local … hospital3@demo.local | hospital12345 |
| Donor | donor00001@demo.local … | donor12345 |

## End-to-end walk-through (Swagger UI or curl)
1. `POST /auth/login` as `hospital1@demo.local` (form fields `username`, `password`) → copy the token → **Authorize**.
2. `POST /hospital/requests`
   ```json
   {"blood_group":"O+","units_required":1,"urgency":"EMERGENCY",
    "required_time":"2027-01-15T10:00:00","max_distance_km":15}
   ```
   (`required_time` must be in the future; naive times are treated as Asia/Kolkata.)
3. `POST /hospital/requests/{id}/find-donors` → top 3 with `score` and `reasons`. Names/phones are `null`.
4. `POST /hospital/requests/{id}/send-requests` → status becomes `REQUESTED`.
5. Log in as one of the returned donors. You only know `D-000123`-style refs, so look up the email as
   `donor{id:05d}@demo.local` (on a fresh seed the numbers should line up with the donor id; if not, check the `donors` table), then `GET /donor/requests`.
6. `POST /donor/requests/{match_id}/respond` with `{"accepted": true}`.
7. Back as the hospital: `GET /hospital/requests/{id}/matches` → the accepted donor's name and phone now appear.
8. `POST /hospital/matches/{match_id}/record-donation` → updates donor history, rating, last-donation date,
   and marks the request FULFILLED when all units are done.
9. If someone declines, call `find-donors` again: contacted donors are skipped, so you get the next-best.

## How matching works (`app/matching.py`, `app/matching_service.py`)
**Hard filters (SQL/PostGIS; never overridden by scores):** blood group · verified donor · status AVAILABLE ·
minimum interval since last donation · within the request's max distance (`ST_DWithin` on a GiST-indexed geography) ·
not already contacted for this request.

**Travel policy:** NORMAL respects the donor's own radius (weekend radius on Sat/Sun); URGENT allows 1.5×;
EMERGENCY allows anything within the hospital's max distance.

**Soft score (0–100), weights in `.env`:** distance 30% · availability/preferred hours 20% · reliability
(response + acceptance rate) 20% · travel compatibility 10% · ML acceptance probability 10% · rating 10%.
With no ML model, its weight is redistributed. Ties break deterministically (score, distance, id).
Rates are smoothed so a donor with 1 request and 1 reply doesn't show 100%.

## Privacy and trust
- Roles: DONOR / HOSPITAL / ADMIN, JWT auth, bcrypt hashes, role checks on every route.
- Hospitals see only `D-000123`, blood group, distance, rating, response rate and score until the donor
  accepts. All of this is decided in one place: `app/views.py`.
- Donors never see matches that haven't been sent to them. Only **verified hospitals** can create requests
  and only **verified donors** can be matched (admin: `POST /admin/hospitals/{id}/verify`, `/admin/donors/{id}/verify`).

## Things to know
- **Medical rules are configuration, not logic.** `MIN_DONATION_INTERVAL_DAYS` (default 90) is a placeholder
  policy value; set it to your blood bank's rules. Donation volume is only ever *recorded* by the hospital.
  Registration requires age ≥ 18 purely as a legal-consent check. Blood group matching is exact, with no
  compatibility substitution, because that is a clinical decision.
- Tables are created at startup for convenience. For production, add Alembic migrations.
- The first 200 nearest eligible donors are scored (`MAX_CANDIDATES`); raise it for larger pools.
- Change `SECRET_KEY` and the admin password before deploying anywhere.

---

# Phase 2: real-time

## Try it (2 minutes)
After `docker compose up --build` and the seed step, open **http://localhost:8000/demo** (use two browser
windows side by side if you like):
1. Hospital pane → **Log in** → **1. Create request** → **2. Find top 3** → **3. Send requests**.
2. Click a donor card in the hospital list. It fills the donor login. Donor pane → **Log in**. The pending
   request is already listed.
3. Send requests again from a second request (or log in as another top-3 donor in another tab). The donor
   pane shows the request **without refreshing**.
4. Donor clicks **Accept**. The hospital card flips to ACCEPTED and the donor's name and phone appear, live.
5. Hospital clicks **Record donation**. The request becomes FULFILLED and other pending donors get a "closed" push.

## How it works
```
REST route (sync) --commit--> notifications.py --> hub.publish(user_id, event)
                                                     |-- in-memory:  delivered on this worker's sockets
                                                     '-- Redis pub/sub: delivered by whichever worker holds the socket
Browser <== ws://host/ws?token=<JWT> ==> hub (one set of sockets per user)
```
| Event | To | Fired when |
|---|---|---|
| `request.new` | donor | hospital sends requests |
| `match.responded` | hospital | donor accepts/declines (includes contact details only if accepted) |
| `request.updated` | hospital | donation recorded, or request closed |
| `request.closed` | donors with a pending ask | request fulfilled or cancelled |

- **Auth:** the socket takes the same JWT as the REST API (`?token=`). A bad or expired token is rejected (close code 4401).
  Each user receives only events addressed to their own user id.
- **Heartbeat:** the client sends `ping` about every 30 s and gets `{"type":"pong"}`. A connection idle for 90 s is closed (4408).
  The demo page reconnects automatically.
- **The database is the source of truth.** Pushes are best effort and a failed push never fails the API call.
  After any reconnect the client should re-fetch over REST (the demo page does), so nothing is lost while offline.
- **Presence:** hospital match lists include `donor_online` (green dot). That means connected now, not guaranteed to reply.
  With Redis it is a key with a 90 s TTL refreshed by heartbeats; without Redis it is read from this worker's sockets.
- **Redis is optional.** `REDIS_URL` unset → in-memory (fine for one worker). Set but unreachable at startup → warning,
  then in-memory. You need Redis once you run more than one uvicorn worker or API container.
- Tests (no DB, Redis or FastAPI needed): `python3 -m unittest discover -s tests -v` (25 tests).

## Phase 2 caveats
- Offline donors get no push (no mobile/web push yet). They see pending requests the next time they open the app.
  Real push notifications (FCM / SMS) would be a later add-on.
- Tokens in a WebSocket URL can show up in server logs. Fine for a college project; for production, use a short-lived
  ticket endpoint or a subprotocol header.
- More donors can accept than units needed. The hospital chooses who to proceed with, and recording the last unit closes the rest.
- `/demo` is a dev tool. Set `ENABLE_DEMO_PAGE=false` in production.

---

# Phase 3: React frontend (`frontend/`)

React 18 + TypeScript + Vite + Tailwind + React Query + React Router + Leaflet. Needs Node 18+.

```bash
cd frontend
cp .env.example .env        # VITE_API_URL=http://localhost:8000
npm install
npm run dev                 # http://localhost:5173
```
Keep the backend running (`docker compose up`) and seeded. Log in with the demo accounts above.
(`npm run build` also type-checks the project.)

## What you get
- **Login** that routes by role (hospital → `/hospital`, donor → `/donor`).
- **Hospital dashboard:** create a request, list your requests, **Find donors** (top 3 with score and reasons),
  **Send requests**, live status chips, online dot, contact details after acceptance, **Record donation**, cancel.
  A Leaflet map shows your hospital, the max-distance circle, and one ring per donor at their distance.
  Donor coordinates are never sent to hospitals, so the map shows rings instead of pins.
- **Donor dashboard:** availability switch, incoming requests with **Accept / Decline**.
- **Live updates:** one WebSocket per tab (`useRealtime`). Every server event, and every reconnect, re-fetches
  the data over REST with React Query, so the screen is always consistent with the database.
- Backend addition: `GET /hospital/me` (name, address, coordinates, verified flag) for the map and the pending-verification notice.

## Not in this first frontend (ask if you want them)
Registration screens (use `/docs` → `/auth/register/*`), an admin verification screen (use `/docs`),
request history and filters, donor profile editing beyond availability, and frontend tests.

---

# Phase 4: XGBoost acceptance model

**Question the model answers:** *"If this donor is asked about this request, how likely are they to accept?"*
That probability becomes one weighted component of the ranking (default 10%, `W_ML`). It never overrides the hard
eligibility filters, and with no model the system quietly ranks with the rules alone.

## Train and use it
```bash
docker compose build backend                      # picks up numpy / scikit-learn / xgboost
docker compose up -d
docker compose exec backend python -m app.ml.train        # about 1 minute, writes backend/models/
```
Then call **Find donors** as before. Each match now includes "Predicted acceptance 87%" in its reasons and an `ml`
entry in its score components. Admin endpoints: `GET /admin/ml/status` (metrics, feature importance) and
`POST /admin/ml/reload` (load a new model without restarting).

## What's inside (`backend/app/ml/`)
| File | Role |
|---|---|
| `features.py` | The 13 model inputs (distance, radius, distance/radius, preferred-hours match, rating, response and acceptance rate, donation count, avg reply time, days since last donation, urgency, hour, weekend). One definition shared by training and serving. |
| `simulate.py` | Synthetic history of request → donor → accepted? Donors have a **hidden** willingness trait the model never sees, so it must infer it from history. |
| `train.py` | XGBoost with early stopping and **monotone constraints** (closer never lowers the probability; better response/acceptance history never lowers it). |
| `evaluate.py` | AUC, log-loss, Brier, plus the metric that matters for ranking: expected acceptance among the top 3 donors contacted. |
| `scorer.py` | Loads the model for the API. Missing, corrupt, or mismatched model → rules-only ranking, never an error. |

Train, validation and test data each use **separate donor pools**, so the test score is on donors the model has never seen.

## Reading the results
`train.py` prints a table like this. The numbers below came from a quick check in my sandbox using
scikit-learn gradient boosting as a stand-in, because XGBoost couldn't be installed there, so treat them as indicative.
Your XGBoost run prints its own.
```
AUC 0.785  (ceiling if hidden traits were known: 0.813)    log-loss 0.546 vs 0.678 for the base rate
Expected acceptance among the top 3 contacted donors:
  random 0.41 | rules_only 0.68 | hybrid_10pct_ml 0.70 | hybrid_30pct_ml 0.73 | ml_only 0.76 | oracle 0.80
```
How to read it: rules alone already beat random by a lot. Adding ML helps, and a larger ML weight helps more
*on this simulation*. To try it, set `W_ML=0.30` in `.env` (weights are normalised, so only the ratio matters).

## Honest caveats (please keep these in your write-up)
- **All training data is simulated.** The acceptance rule is my assumption, so these scores show the pipeline can
  recover a simulated pattern, not that it predicts real donors. Say "trained on a simulated dataset" on your resume
  and in your demo.
- The simulation is somewhat circular (the model learns the rule I wrote). The meaningful, defensible parts are the
  engineering ones: leak-free split by donor, ablation of rules vs ML vs hybrid, monotone constraints, graceful
  fallback, explainable output.
- **Retraining on real data** needs the feature values saved at request time. Today only the final accepted/declined
  response is stored. The clean next step is a `features` JSONB column on `matches` (needs an Alembic migration, since
  `create_all` won't alter existing tables). It isn't built.
- Medical eligibility is still decided only by the hard filters and hospital verification, never by the model.
