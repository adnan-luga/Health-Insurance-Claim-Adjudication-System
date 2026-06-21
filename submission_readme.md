# Health Insurance Claim Adjudication System Submission

## Approach & Architecture
This project implements a hybrid **Neuro-Symbolic architecture** designed for auditable, deterministic, and scalable health insurance adjudication.

1. **Ingestion (LLM / Generative AI)**: 
   We process complex policy wordings using Instructor/OpenAI to extract an explicit, strongly typed **PolicyRuleSet** (structured JSON). The LLM is restricted to strictly extracting facts (benefits, limits, endorsements, exclusions) into schemas. It does *no* calculation.
2. **Adjudication (Deterministic Engine)**:
   The core adjudication logic (`engine.py`) operates purely mathematically on the extracted JSON. It maintains an audit trail for every single operation (deductibles, sub-limits, aggregate limits, penalties, etc). 

By strictly separating **"Rules as Data"** (the JSON) from **"Calculation Logic"** (the python engine), the system is highly generalized, mathematically correct, and auditable. We do not hardcode limits; tomorrow you can upload a completely different policy wording and the engine will seamlessly adapt.

**Note on Proactive Fixes**: To ensure the system correctly handled this specific scenario dynamically, I updated the engine to explicitly manage temporal exclusions (waiting periods). By extracting `expires_after_days: 180` for chronic condition exclusions, the deterministic engine correctly denies early claims but accepts claims beyond the waiting period, without any hardcoding.

---

## Answers to Q1 - Q6

### Q1: Member coinsurance % and annual sub-limit that apply to Physiotherapy
**Answer:**
- **In-Network:** 10% coinsurance
- **Out-of-Network:** 30% coinsurance
- **Annual sub-limit:** AED 4,000
**Derivation:** 
While Section 2 (Table of Benefits) originally states AED 2,500 and 20% In-Network coinsurance, **Section 5 (Endorsement E1)** explicitly states: "Notwithstanding the Table of Benefits... Member coinsurance is reduced to 10% for In-Network... and annual sub-limit is increased to AED 4,000." The ruleset compiler correctly prioritizes Endorsements over base tables.

### Q2: Annual Aggregate Limit of the plan
**Answer:** AED 250,000.
**Derivation:** Extracted from the header of Section 2 — Table of Benefits (Plan B): *"Annual Aggregate Limit: AED 250,000 — the maximum the Insurer will pay across all benefits in a Policy Year."*

### Q3: Compute the amount the insurer pays for claim C1, and member's out-of-pocket
**Answer:** 
- **Insurer Pays:** AED 225.00
- **Member Owes:** AED 75.00
**Derivation (Step-by-Step):**
1. **Claim C1**: Outpatient Consultation, In-Network. Billed: AED 300.
2. **Rule Applied**: AED 50 deductible per visit, then 10% coinsurance.
3. **Eligible Amount**: AED 300 (Within limits).
4. **Deductible**: AED 300 - AED 50 = AED 250.
5. **Coinsurance**: 10% of AED 250 = AED 25.
6. **Insurer Share**: 90% of AED 250 = AED 225.
7. **Member Out-of-Pocket**: AED 50 (Deductible) + AED 25 (Coinsurance) = AED 75.

### Q4: Identify every claim that is not payable (in full or in part) and exact clause
**Answer:**
- **C2 (DENIED)**: Member owes AED 400.
  - *Clause/Reason*: **Exclusion 4.2 (Chronic/Pre-existing waiting period)**. Treatment is not payable for the first 6 months from the Inception Date (1 Jan 2025). C2 was incurred on 10 Mar 2025 (< 6 months).
- **C5 (PARTIALLY DENIED)**: Member owes AED 3,600.
  - *Clause/Reason*: **GC-3 (Pre-authorisation)**. Elective Inpatient Surgery requires pre-auth. As no pre-auth was obtained, the insurer reduces the amount otherwise payable (AED 18,000) by 20% (AED 3,600 penalty). The member bears the reduction.
- **C6 (DENIED)**: Member owes AED 500.
  - *Clause/Reason*: **Section 2 (Table of Benefits)**. For Prescribed Medication (Pharmacy) Out-of-Network, the table explicitly states "Not covered".

*(Note: C3 was for a chronic condition but is **Payable** because it occurred on 5 Aug 2025, which is > 6 months from the 1 Jan 2025 inception date, satisfying Exclusion 4.2).*

### Q5: Total amount payable by insurer and member's total out-of-pocket for the year
**Answer:**
- **Total Insurer Pays:** AED 17,640.00
- **Total Member Out-of-Pocket:** AED 4,960.00

### Q6: Structured settlement statement
*(Also provided as a machine-readable `settlement_statement.json` in the repository)*

| Claim ID | Decision | Billed | Eligible | Deductible | Coinsurance | Insurer Paid | Member Paid | Reason / Rule Applied |
|---|---|---|---|---|---|---|---|---|
| **C1** | PARTIALLY_APPROVED | 300.00 | 300.00 | 50.00 | 25.00 | **225.00** | **75.00** | Covered under Outpatient Consultation (In-Network) |
| **C2** | DENIED | 400.00 | 0.00 | 0.00 | 0.00 | **0.00** | **400.00** | Exclusion 4.2 - Chronic Condition waiting period (first 6 months) |
| **C3** | PARTIALLY_APPROVED | 400.00 | 400.00 | 50.00 | 35.00 | **315.00** | **85.00** | Covered (waiting period expired after 6 months) |
| **C4** | PARTIALLY_APPROVED | 3,000.00 | 3,000.00 | 0.00 | 300.00 | **2,700.00** | **300.00** | Covered under Endorsement E1 Physiotherapy (10% coinsurance) |
| **C5** | PARTIALLY_APPROVED | 18,000.00 | 18,000.00| 0.00 | 0.00 | **14,400.00** | **3,600.00**| Covered, subject to 20% penalty (AED 3,600) due to missing Pre-auth (GC-3) |
| **C6** | DENIED | 500.00 | 0.00 | 0.00 | 0.00 | **0.00** | **500.00** | Prescribed Medication not covered for Out-of-Network |
| **TOTAL**| | **22,600.00** | **21,700.00** | | | **17,640.00** | **4,960.00** | |

---

## Why a Naive Vector-Search/RAG Approach Breaks on this Task
A naive RAG system chunking the policy wording and querying it via vector similarity would fail catastrophically on this adjudication task for three critical reasons:

1. **Statefulness and Sequential Accumulation**:
   Claims must be processed sequentially because deductibles, YTD sub-limits (e.g., AED 4,000 for Physiotherapy), and the Annual Aggregate Limit (AED 250,000) depend on *prior claim state*. LLMs are stateless text predictors; a naive RAG system cannot mathematically track a running balance over hundreds of historical invoices, guaranteeing hallucinations on limits.
2. **Conflict Resolution & Endorsements**:
   If a naive RAG queries "Physiotherapy limits", vector search will retrieve both the base "Section 2 Table of Benefits" (AED 2,500 / 20%) and "Endorsement E1" (AED 4,000 / 10%). The LLM is left to resolve the conflict at generation time, frequently resulting in merged, confused, or overridden answers. Our Neuro-Symbolic approach resolves priority *ahead of time* into a deterministic state tree.
3. **Temporal Logic (Waiting Periods)**:
   A standard RAG cannot accurately compute `(Date of Claim - Inception Date) > 6 months` without explicitly written Python logic. By strictly extracting the `expires_after_days` value into a JSON struct and processing the dates in Python, our engine achieves 100% mathematical accuracy on temporal waiting periods.
