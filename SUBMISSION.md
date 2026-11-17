# Contract Desk (RO) — submission, Legal track

**One line:** a contract-review skill for Romanian-law documents that quotes the risk instead of
inventing it — deterministic rule engine underneath, legal model on top.

**Track:** Legal · **Status:** working today, runs offline, no API key required for the core.

---

## 1. The problem

A small company signs a supplier contract and finds out two years later that liability was
unlimited, the term renewed itself, and the forum was London. Reviewing every contract properly
costs more than the contract is worth, so it is skipped until something breaks.

Generic AI tools answer this with a fluent summary that sounds right and cites nothing. In legal
work that is worse than no answer: a missed clause costs money, an invented one costs trust.

## 2. What it does

```
contract (.docx/.pdf/.txt)
   ↓ extract + segment into numbered clauses
   ↓ 13-rule risk checklist (deterministic, offline, same output every run)
   ↓ 13 findings, each with an exact quote, severity, why it matters, position to take
   ↓ memo (.docx) + triage sheet (.xlsx) + anonymised copy (.docx) + findings (.json)
```

The split is deliberate: **the rule engine finds and quotes; the model judges and drafts.**
Every quote is an exact slice of the user's document, so nothing can be paraphrased into
existence. The model is used where it is strong — negotiating strategy, counter-clauses,
explaining to a non-lawyer — not where it hallucinates.

## 3. What already works (measured, not planned)

Run on the bundled synthetic contract (`data/sample_contract.docx`):

| Metric | Value |
|---|---|
| Clause units recognised | 35 |
| Findings | 13 — 5 high, 6 medium, 2 low |
| Entities anonymised | 15 (companies, CUI, Reg. Com., IBAN, e-mail, phone, address) |
| End-to-end runtime | 1.43 s for the whole document, all four artifacts |
| Determinism | identical findings from the `.docx` and from its `.txt` export |

Findings it actually produced on that contract: no liability cap at all (R01), unlimited liability
including lost profit (R02), unilateral price amendment (R04), English law and London courts
(R08), personal data with no processing agreement (R10), 90-day payment term (R05), 1%/day
penalty (R06), automatic renewal without notice (R03), IP assignment over future works (R09),
assignment without consent (R12), unlimited confidentiality (R11), no defined notice channel
(R13), no termination right (R07).

## 4. How AutoClaw is used

- **As a skill** (`skill/SKILL.md`): the whole pipeline is one repeatable instruction — "review
  this contract" — so the workflow is not re-explained every session.
- **As the judgement layer**: findings feed the legal model for negotiation strategy and
  counter-drafting, which is exactly the step that needs language, not matching.
- **As the delivery surface**: memo and spreadsheet come out as files the user forwards to a
  lawyer, plus a redacted copy safe to send outside.

AutoClaw ships a legal-specialised model ([GLM-5.3-flashX-Legal](https://autoclaw.z.ai/blog)),
which is what makes the judgement step credible on Romanian/CEE commercial text.

## 5. Why this is not a wrapper

- The rule engine is auditable: 13 rules, each with the pattern, the severity and the fix in
  plain language; no black box between the contract and the quote.
- Absence is treated as a finding — three rules fire on what the contract *does not say*
  (no cap, no termination right, no notice channel), which is where real damage hides.
- Romanian-specific: diacritic-insensitive matching with length-preserving folding, so quotes map
  back to the original text byte-for-byte; redaction covers CUI / Reg. Com. / IBAN formats.
- Zero external calls in the core: it runs on a laptop, on a client's machine, with no data
  leaving the device — the usual blocker for legal work.

## 6. Limits (stated, not hidden)

13 rules is a triage checklist, not a legal review; natural-person names are not redacted; scanned
PDFs need OCR that is not wired in; clause segmentation is heuristic. Output is a memo for a human
decision — a lawyer still signs.

## 7. Next

Rule pack as YAML (a firm loads its own checklist) · counterparty-redline diff mode ·
public-procurement checklist once citations are verified.

---

## Pe scurt (RO)

Uneltele de AI juridic inventează articole de lege și omit clauze. Aici riscul e găsit de un motor
determinist — 13 reguli pentru contracte B2B românești — care citează exact textul, iar modelul
juridic din AutoClaw face partea de judecată: ce ceri la negociere și cum formulezi
contra-propunerea. Pe contractul demo: 35 clauze, 13 constatări (5 ridicate), 15 entități
anonimizate, 1,43 s. Rezultatul e un memorandum, un tabel de triaj și o copie anonimizată.
