# Frontend console

Phase 10 extends the existing React + TypeScript + Vite app. It calls the Phase 1–9 API through the Vite proxy (`/api` → `http://127.0.0.1:8000`). It does not invent endpoints or successful sandbox/rollback/persistence results.

## Views

| View | Backend routes used |
| --- | --- |
| Data sources | `GET /api/v1/sources`, `GET /api/v1/sources/bookstore-demo/schema` |
| New migration | `POST .../plans`, `.../risk`, `.../artifacts`, `.../sandbox`, `.../rollback`, `.../report`, `.../workflows` |
| History / detail | `GET /api/v1/workflows`, `GET /api/v1/workflows/{id}`, `GET .../audit` |
| Settings | `GET /api/v1/health` |

Hash routes: `#sources`, `#migration`, `#workflows`, `#workflow/{id}`, `#settings`.

## Contracts used for Phase 9

| Method | Path | Body |
| --- | --- | --- |
| POST | `/api/v1/sources/bookstore-demo/artifacts/{migration_id}/workflows` | `{ "request": string, "confirm": true }` |
| GET | `/api/v1/workflows` | none |
| GET | `/api/v1/workflows/{workflow_id}` | none |
| POST | `/api/v1/workflows/{workflow_id}/approvals` | `{ "target_identity": string, "confirm": true }` |
| GET | `/api/v1/workflows/{workflow_id}/audit` | none |

Sandbox and rollback still require `{ "confirm": true }`. Safety report requires `{ "request": string, "confirm": true }`.

## Optional LLM assist

The migration wizard can send `use_llm: true` on plan, risk, artifact, report, and persist calls. The UI shows the original request, model suggestion (when present), interpretation path, provider status/errors, and the deterministic plan/risk results. An LLM suggestion is never treated as approval. Settings shows `llm_enabled` / `llm_configured` / provider / model from health without exposing keys.

## Safety rules in the UI

- Wizard values are temporary session state until a workflow is persisted.
- Generated artifacts are shown with `applied: false`.
- Sandbox and rollback require an explicit checkbox confirmation.
- Rollback statuses are shown as `exact_restoration`, `partial_restoration`, `failed`, or `not_verified`.
- `not_verified` is never labeled success.
- Partial restoration shows that recreating a dropped column does not restore former values.
- Approval is blocked while `authentication_available=false` (from health and backend policy). The console does not invent an approver identity or treat a click as a verified human approval. The backend also rejects approval recording without authentication.
- Application-database failures surface the real API error and do not invent history.

## Commands

```powershell
cd frontend
npm install
npm test
npm run build
npm run dev
```

Target execution is not offered in the UI.
