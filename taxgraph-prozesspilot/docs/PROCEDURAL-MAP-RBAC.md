# Procedural Graph v3 integration and three-role access (Hackathon MVP)

## Status

**Code change is a review branch, not a deployed system.** The URL `https://34-38-10-198.sslip.io/#graphs` was inspected as a rendered page, not as an authenticated machine-readable API. `/api/procedural-map` returns a **curated v3 node mapping**. This is *not* a complete remote graph import or a claim that all remote edges are known. No MCP tools are invoked; no API key is exposed.

`app/procedural_map.py` maps the 17 observed external nodes into the original `prozessGraph` audit process and the existing Fachprüfung V2's substantive legal-test graph. It identifies the separate `SHARE_TAX_RIGHT` (§1(4)) and `TAXRIGHT` (§20(2)), timing, net-negative-asset upvaluation and tax-consequence branches. Note: `c_aufstockung` is **not** independently computed yet; its mapping is marked review-required. The V2 engine does not currently accept net-negative assets as a positive path. Do not change a published legal graph or silently permit an unsupported Wertansatz.

## Roles and scope

| Role | Access |
|---|---|
| `viewer` | View published processes and own organization's synthetic cases/runs; cannot edit or execute |
| `editor` | View/edit own organization's processes, create a new draft process, fork existing published or draft processes; edit/run cases; cannot publish or approve |
| `reviewer` | View/edit/fork own organization's existing processes and publish reviewed drafts; approve case decisions; cannot create new process or case |

Existing published graphs are immutable: editing is copy-on-write through `POST /api/graphs/{id}/draft`. The reviewer role is **technical review permission**, not proof of tax-law expertise.

All graph versions and cases have `org_id`. Existing rows migrate to the special `demo` organization. Cross-org direct-object URL access is denied with 404; the API identifies the actor from verified credentials, disregarding supplied `actor` and `reviewer` names. A case's detailed Fachprüfung is organization-scoped. The old global activity stream is unavailable in production because it mixes organizations; this is a known limitation requiring an org-scoped activity schema later.

## Provisioning

**Local development**: `APP_ENV=local` (default) supplies one privileged `demo` actor to preserve existing synthetic tests and offline demo behavior. **Do not expose local mode publicly.**

**Production**: `APP_ENV=production` requires at least one provisioned account; the server refuses startup otherwise. Use HTTPS and reverse-proxy security controls; HTTP Basic credentials are otherwise exposed in transit. Passwords are hashed with scrypt and entered through hidden prompts:

```bash
cd taxgraph-prozesspilot
python scripts/manage_users.py add-user alice demo viewer
python scripts/manage_users.py add-user bert demo editor
python scripts/manage_users.py add-user carla demo reviewer
python scripts/manage_users.py add-org team-b "Team B"
python scripts/manage_users.py add-user dora team-b reviewer
```

Provision before setting `APP_ENV=production`. Remove legacy `APP_PASSWORD` and `APP_USER` settings from public deployments; unlike the prior single-demo password, these are not the production identity store. There is no self-registration or UI-based role administration. The basic authentication implementation is a Hackathon prototype, **not** a production identity platform: add SSO/MFA, password rotation, account recovery, rate limiting, session management, trust-anchored audit logs, and data-protection review before deploying to real clients. Only synthetic cases.

## API examples

- `GET /api/config` exposes current identity and capabilities.
- `GET /api/procedural-map` exposes curated source-to-rule mapping with unresolved gaps.
- `POST /api/processes` with `{"label":"Mein Prozess"}`: editor-only, creates a distinct draft based on the existing §20 demo template.
- `POST /api/graphs/{id}/draft`: editor or reviewer, creates an editable version in the same organization.
- `PUT /api/graphs/{draft}`: editor or reviewer, server-verified author.
- `POST /api/graphs/{draft}/publish`: reviewer-only; client must confirm structural review.

All privileged rules are checked server-side. Frontend control visibility is convenience only.

## Known limitations

- Separate live MCP schema/edge discovery is required before automating external graph imports.
- Tax rules and mathematical upvaluation require professional validation; import is intentionally non-authoritative.
- Org isolation for old global activity logs requires future schema migration (the endpoints are blocked in production).
- API users currently authenticate via HTTP Basic, not via an established identity provider.
- Historical audit identities from pre-RBAC demo runs are not retroactively attested.
- Regression tests have been added but need CI execution before merging to `main`.
