# Fachprüfung V2 · § 20 UmwStG — scope and audit model

**Implementation date:** 2026-10-17. **Legal sources:** [§ 1 UmwStG](https://www.gesetze-im-internet.de/umwstg_2006/__1.html), [§ 20 UmwStG](https://www.gesetze-im-internet.de/umwstg_2006/__20.html), [§ 22 UmwStG](https://www.gesetze-im-internet.de/umwstg_2006/__22.html), [§ 23 UmwStG](https://www.gesetze-im-internet.de/umwstg_2006/__23.html), [§ 152 UmwG](https://www.gesetze-im-internet.de/umwg_1995/__152.html), [BMF UmwStE 02.01.2025](https://www.bundesfinanzministerium.de/Content/DE/Downloads/BMF_Schreiben/Steuerarten/Koerperschaftsteuer_Umwandlungssteuer/2025-01-02-umwStE.pdf?__blob=publicationFile).

The extension **retains the existing ProzessPilot 19-node / 35-edge executor**, its audit endpoints, and its published graph versions. It **adds** a deterministic, explicit Legal Reasoning Graph for the typical synthetic *eingetragener Einzelkaufmann → GmbH* transaction. The original process graph is **not renamed or silently represented as fully legally complete**.

## Running the supplement

Install `apply_completion.py` from the download package on a clean checkout. Start the original app and use **Fachprüfung §20 V2** or visit `/fachpruefung`. Choose a synthetic Musterfall A–D and provide the additional reviewed facts. For a demonstration, use **Beispiel A synthetisch ergänzen**. These inputs are *assumptions*, not evidence authenticated by this software. Execute, compare the three value branches, and inspect the graph and audit report.

API:

- `GET /api/fachpruefung/schema` — supported additional facts, grouping, supported legal as-of
- `POST /api/cases/{case_id}/fachpruefung` — run legal reasoning on the original case facts plus reviewed supplemental facts; body: `{ "extra_facts": {"transaction_type": {"value": "ausgliederung", "verification": "confirmed", "evidence_ref": "SYNTHETISCH: ..."} } }`
- `GET /api/cases/{case_id}/fachpruefung/latest` — retrieve latest immutable snapshot
- `GET /api/cases/{case_id}/fachpruefung/{run_id}` — retrieve a particular saved snapshot
- `GET /api/cases/{case_id}/fachpruefung/{run_id}/export` — full JSON, facts, source versions, nodes, edges, replay hashes

`legal_assessment_runs` is an additive table in the same SQLite DB. Historical runs are never overwritten. Retrieval checks whether their inherited original case facts still match the current case and displays a stale-result warning without changing the old snapshot. Full reports contain the original inputs, assessment results, typed legal/evidence/consequence nodes, the actual dependencies between them, a legal source map, and local integrity hashes. `verify()` independently reconstructs the deterministic report from the saved inputs; neither it nor local hash chaining establishes external immutability, reviewer identity, or correctness of legal interpretations. The original reviewer gate does not automatically approve V2. **Do not treat a legacy approval as a completed V2 assessment.**

## Covered Prüfschema

| Original Prüfschema | Implementation | Hard limits |
|---|---|---|
| Schritt 0, § 16 EStG | Separate fair-value baseline and preliminary gain with booked transfer costs; § 4 Abs. 3 change warning | Final taxable result, individual §16 allowances / §34 rates not automated |
| Schritt 1, UmwG | Distinct § 152 e.K. Ausgliederung checks, evidence of actual Handelsregister-Eintragung (separate from Anmeldung), and Einzelrechtsnachfolge branch | Corporate registration validity, creditor protection, employment law require human review |
| Schritt 2, § 1, § 20 Abs. 5/6 | Recipient/transferor alternative eligibility; 8-month date-check with **register filing** vs **contract+economic transfer**, temporal block outside 2025–2026 | Qualified German treaty/cross-border analysis requires human review |
| Schritt 3, § 20 Abs. 1/2 | New shares, essential assets, four lower-value conditions, consideration cap, application, 3 paths | Nonzero post-effective-date deposits/withdrawals block automatic gains pending asset-level reconciliation |
| Schritt 4, § 23, § 27 | Recipient valuation and correct depreciation-method description; separate capital-reserve reporting | No asset-level AfA or finalized §27 computation without asset/subsidiary ledgers |
| Schritt 5, § 20 Abs. 3/4 | Conditional transferor gain, shares basis, normal vs reduced-rate eligibility flags | Income tax / special deductions and special tax-right exceptions need expert review |
| Schritt 6, § 22 | Actual share-sale EGI I; full completed **time years**, partial transfers, acquisition-cost correction; 7 annual proof due dates | Replacement events, deemed disposal for missed proof, chain contribution, §23(2) raise require expert review; an overdue deadline is *not* automatically a confirmed failure |

All successful valuations indicate `READY_FOR_EXPERT_REVIEW`, not professional approval. Unknown/unverified facts cannot unlock a tax outcome. Conflicting observations block a positive finding. A failed lower-value test does not prevent *common value* as the statutory default if the **base application scope** is satisfied.

## Deterministic tests / golden cases

Run `python -m pytest -q tests/test_legal_reasoning.py tests/test_legal_review_api.py` from `taxgraph-prozesspilot/` after applying overlay. Core tests include:

- Typical case, three value branches, distinct GmbH and Einbringender consequences
- § 152 registration/solvency, personal scope alternative, eight-month temporal cutoff
- Lack of evidence, conflicting testimony, and unsupported historical law years
- Consideration upper limit with currency-cent precision
- Full/partial disposal in §22, separate retroactive tax year and share-sale cost basis
- Anniversary boundary and all seven annual proof obligations
- Tamper detection and deterministic replay

## Non-goals / legal restrictions

No claim of fully complete German tax expertise, Rechtsberatung, tax-filing readiness, tax authority acceptance, TaxGraph live access, DATEV integration, GDPR compliance for client data, or professional reviewer attestation. **Synthetic cases only.** Any future shift toward actual clients requires the existing privacy, professional secrecy and legal governance review.

**Architecture note:** The new graph is a materialized *proof/dependency graph*. Nodes include `Fact`, `Evidence`, `LegalProvision`, `LegalTest`, `Assessment`, `Decision`, `TaxConsequence` and `Obligation`. Unlike simple routing labels, `INPUT_TO`, `SUPPORTS`, `GOVERNS`, `EVALUATES` and `TRIGGERS` edges represent the dependencies used for each reported assessment or consequence. The trusted evaluator is explicit Python, not `eval()`/LLM execution. The original diagram continues to be a process graph.
