# Functional Integration V3 - scope, architecture and evidence

## Delivered boundary

The current homepage and `/prozesse` execute **one process package through one V3
legal assessor**. This is no longer a node mapping catalog: branches call bound
legal assessments, produce four-state outcomes and record every candidate edge,
selected transition, calculation, source snapshot and independent safety gate.
The 17 observed source node IDs are retained; 7 explicit local normalization
nodes make 24 local nodes and 65 local edges. These are NOT claimed to be the
remote graph's original edge count or topology.

**Unresolved external dependency:** a complete authenticated/verified export of
`einbringung_par20_umwstg v3` could not be obtained in this environment. Browser
connector access failed and public fetch was unavailable. The shipped package
therefore declares `UI_OBSERVED_NO_FULL_EXPORT`, `complete=false`, `raw=null`.
A real complete export can be imported into a draft; node identity, binary
branches, reachability, cycles, size and credential-like fields are validated.
The raw graph and all edge metadata are frozen and hashed. Every source edge
receives an explicit coverage disposition; source prose is NEVER executed.
A schema mismatch is rejected, not guessed. No remote MCP write is performed.

## Architecture decision (ADR-003)

Observed root cause: the original graph executor hard-coded a positive BALANCE
node and a fixed set of IDs, while the V2 assessor separately computed legal
consequences. A catalog did not bridge the executions. Adding a fourth patch to
that structure would preserve two competing authorities.

Decision: a new immutable process-package contract orchestrates a version-pinned
successor to the existing assessor. `functional_graph.run()` invokes
`legal_v3.assess()` exactly once. Only registered legal-test bindings execute;
JSON cannot install code, change a rule binding, bypass unknown/conflicted
branches or silently change the normalized legal assumptions. A mandatory
path gate and publication-time golden cases prevent positive shortcuts.

- `functional_graph.py`: closed bindings, source-import contract, DAG validation,
  real branch execution and deterministic replay.
- `legal_v3.py`, `valuation.py`: the single current legal assessment and decimal
  valuation handlers. No live network access in execution.
- `functional_api.py`: tenant-scoped packages, input snapshots, runs, optimistic
  concurrency, version events and human decisions.
- `functional_golden.py`: independent synthetic reference amounts and paths,
  also used as the package-publication gate.
- `functional.html/js/css`: role-aware process library, case input, actual
  execution graph, evidence/guard inspector, historical runs and approvals.

The V1 executor and `legal_reasoning.py` V2 are deliberately unchanged. `/studio`
and `/fachpruefung` retain their old demo/replay interfaces; they are marked
historical, not alternative current authorities. An old assessment is never
upgraded in place. Future V4 development must retain the V3 source modules or
an archived runtime: matching a schema string alone is not replay compatibility.
Exports contain source/handler hashes; the repository commit retains the code.
Local hashes are NOT an externally signed audit archive.

Reference practices: immutable event history and deterministic replay
[Temporal](https://docs.temporal.io/encyclopedia/event-history), explicit workflow
versioning [Temporal workflows](https://docs.temporal.io/workflows), and
[OWASP authorization](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html).
No Temporal service or new distributed infrastructure was introduced.

## Legal research and deliberate normalization

Jurisdiction: Germany. Synthetic sole-proprietor scenario, supported transfer
years 2025/2026 only. This is NOT tax advice or blanket coverage of all UmwStG
transactions. Reviewer permission does not attest professional qualification.

Primary sources checked:
- [UmwStG 1](https://www.gesetze-im-internet.de/umwstg_2006/__1.html): separate
  recipient incorporation/seat/management from the contributor alternatives.
- [UmwStG 20](https://www.gesetze-im-internet.de/umwstg_2006/__20.html): scope,
  valuation, application, consideration, share basis and effective dates.
- [UmwStG 22](https://www.gesetze-im-internet.de/umwstg_2006/__22.html): actual
  disposal events, retroactive consequences and proof obligations.
- [BMF UmwStE 02.01.2025](https://www.bundesfinanzministerium.de/Content/DE/Downloads/BMF_Schreiben/Steuerarten/Koerperschaftsteuer_Umwandlungssteuer/2025-01-02-umwStE.pdf?__blob=publicationFile),
  especially 20.19, 20.19a, 22.28-22.33 and 23.14-23.21. The tables on printed
  pages 58 and the valuation/AfA passages were visually inspected.

Key changes relative to the observed source description:

1. **Two tax rights, not one Boolean.** Share-disposal taxing rights participate
   in the section-1 personal-scope alternatives. Asset-disposal taxing rights
   are checked separately under section 20(2) no.3.
2. **Negative net book value is not a permanent lower-value veto.** A complete
   confirmed asset schedule and tax liabilities must reconcile gross assets,
   net book/fair values and uplift capacity. A minimum net value of zero can
   require a forced intermediate valuation (20.19). Tax-book negativity must
   not be confused with civil-law over-indebtedness under UmwG 152.
3. **Excess non-share consideration is not automatically full fair value.**
   Within the bounded model with no withdrawals/contributions: allowance is
   `max(B/4,min(500000,B))`. For excess `E`, minimum net value is at least
   `(1-E/F)*B+E`, zero, and total other consideration, capped by fair-value
   feasibility. Rounding cannot understate the minimum. BMF 20.19a reference:
   B=3m, F=5m, C=1m yields minimum 3.1m, uplift 100k, share basis 2.1m.
   With B=100k, F=5m, C=1m, the additional consideration floor yields 1m.
4. **No silent valuation election.** A missing application offers the fair-value
   path, but does not change a user's requested choice. Statutory minimum uplift
   is shown separately as requested mode versus effective mode.
5. **No silent date substitution.** Ausgliederung uses filing date; other supported
   contributions use contract AND economic-transfer dates. Failed retroactivity
   produces `DATE_CORRECTION_REQUIRED`. A confirmed opt-in plus confirmed actual
   transfer date creates a new assessment; original requested date remains.
6. **Consequences are per subject and year.** Positive hidden reserves are
   allocated proportionally, including zero-book intangible/goodwill entries if
   supplied. Supported linear AfA is an annual illustration using original base
   plus uplift, capped by remaining volume, not a full-year/pro-rata schedule.
   Section 27 KStG is an explicit reconciliation task, not an equation treating
   commercial equity as the tax contribution account. GrESt and general VAT/
   employment law remain explicit manual topics. Section-21 alternative
   classification and complex replacement events remain manual handoffs.

Unsupported combined cases (negative book value plus non-share consideration,
nonzero withdrawals/contributions, hidden losses, pension/special asset treatment,
unsupported historical law) do not get an automatic favorable conclusion.
An absence of proof and conflicting evidence are never converted to `false`.

## Authorization and lifecycle

Production uses the existing named-user authentication over HTTPS. Viewer reads
published same-org packages and synthetic reports; editor creates and edits
same-org drafts and executes cases; reviewer edits/forks same-org processes,
publishes after normalization acknowledgement and golden tests, and documents
case decisions. Reviewer does not implicitly gain new-process creation rights.
Local demo mode retains its clearly labelled demo reviewer identity.

Every process/input/run/export/review route checks organization ownership.
Untrusted request-body author names are not accepted. Browser write requests with
another Origin are denied. Full production identity management (SSO/MFA, recovery,
rate limiting, roles administration) is outside this demo.

Draft updates require the expected content hash; published packages cannot be
overwritten. Source imports, edits and publication have full definition snapshots
in an event chain. Runs freeze package, rules, facts and source. Human approval is
bound to run hash, package, case facts and supplemental input hash. Changing a
case or supplemental inputs makes previous approval ineffective. No historical
run is rewritten or automatically approved.

A controlled learning demonstration can publish a version with
`enable_aufstockung=false`: the complex case stops with `MODEL_REVIEW_REQUIRED`.
An expert then forks the package, enables the reviewed handler, passes reference
cases and publishes. The same complex facts succeed through the new branch;
the old run remains replayable. This is reviewed knowledge activation, NOT
unrestricted autonomous generation or self-modification of tax law.

## Run and verify

Use the existing local startup script. The home page opens the integrated
library. In `Fall pruefen`, choose a synthetic case, apply the normal or negative
net-assets sample, **save**, then execute a published process. Click a path node
to inspect all candidates and supporting assessments. Download the full audit.

```bash
python -m pytest -q
for file in app/static/*.js; do node --check "$file"; done
sh -n start-lokal.sh
# Optional offline DOM+TestClient harness; needs Playwright and Chromium:
CHROMIUM_PATH=/usr/bin/chromium python scripts/verify_functional_dom.py
```

Verification performed on the source in this change:
- 104 local Python/API tests passed (Python 3.13.5), excluding the unchanged
  `test_mcp_client.py`: local `httpx2` / MCP SDK were unavailable. This is not a
  claim that the MCP suite passed. CI retains full-suite configuration.
- JavaScript syntax for every browser script, Python compilation and startup
  shell syntax passed.
- Offline Chromium DOM + real TestClient transport verified author execution of
  the negative-net-assets case, viewer read-only behavior and reviewer approval,
  with zero JavaScript page errors. This is not live-network browser acceptance.
- Live browser navigation to localhost was blocked by the environment's browser
  policy; no bypass was attempted. The earlier baseline CI run was cancelled,
  not counted as passing. No deployment or production security certification.
- Legacy tests were updated where the previous RBAC merge left stale expectations
  of caller-supplied actor names, shared-password production identity, or reviewer
  creation rights. Fiscal V1/V2 tests and engines were not weakened or rewritten.
