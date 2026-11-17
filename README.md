# Contract Desk (RO)

Deterministic contract review for Romanian-law documents, wrapped as an AutoClaw skill.

Most "AI contract review" demos invent statute numbers. This one separates the two jobs:
a **deterministic rule engine** finds and quotes the risk (auditable, offline, same output
every run), and the **legal model inside AutoClaw** does the judgement work (negotiating
strategy, counter-drafting) on top of findings that are already grounded in the text.

## What runs today

| Step | What happens | Output |
|---|---|---|
| 1. Extract | `.docx` (paragraphs + tables), `.pdf` (text layer), `.txt` | plain text |
| 2. Segment | numbered clauses (`1.1`, `Art. 4`, `12.`) into units; falls back to single doc | 35 units on the sample |
| 3. Review | 13-rule checklist for Romanian B2B contracts, severity-tagged | 13 findings on the sample |
| 4. Render | memo, spreadsheet, redacted copy, JSON | 4 artifacts + map |

Verified on the bundled sample: **35 clause units, 3,183 characters, 13 findings
(5 high / 6 medium / 2 low), 15 entities redacted, 1.43 s** end to end, identical results
from the `.docx` and from the `.txt` export.

## Quick start

```powershell
python tools/make_sample.py --out data/sample_contract.docx
python src/ro_contract_review.py --input data/sample_contract.docx --out out
```

Any contract: replace `--input`. `--no-redact` skips the anonymised copy.

## Outputs

- `out/review_memo.docx` — memo: summary, then per finding the quote, why it matters, the position to take
- `out/findings.xlsx` — triage sheet, severity colour-coded, filtered, with a summary tab
- `out/redacted_contract.docx` — same document, parties/CUI/IBAN/addresses replaced (`[COMPANIE_1]` …)
- `out/findings.json` — machine-readable, for the agent layer or an integration
- `out/redaction_map.json` — internal mapping, **never ship it with the redacted copy**

## Rule pack

| ID | Finding | Severity |
|---|---|---|
| R01 | No liability cap anywhere in the document | high |
| R02 | Unlimited liability / all damages, incl. lost profit | high |
| R03 | Auto-renewal without notice period | medium |
| R04 | Unilateral amendment of price or scope | high |
| R05 | Payment term above 60 days | medium |
| R06 | Late-payment penalty above 0.5%/day | medium |
| R07 | No termination-for-convenience right | medium |
| R08 | Foreign governing law or courts | high |
| R09 | IP assignment covering future works | medium |
| R10 | Personal data processed without a data-processing agreement | high |
| R11 | Confidentiality with unlimited duration | low |
| R12 | Assignment without the other party's consent | medium |
| R13 | No defined notice channel | low |

## Design decisions

- **Diacritics-insensitive matching, length-preserving.** Text is lowercased and `ă/â/î/ș/ț`
  are folded 1:1, so match offsets map back onto the original string and every quote is an exact
  slice of the contract — not a paraphrase.
- **One finding per (rule, article).** `12.1` and `12.2` are one negotiating issue, not two rows.
- **Absence is a finding too.** R01/R07/R13 are document-level: the risk is what the contract
  does not say, so the quote reads `(clauză absentă din document)`.
- **No legal citations in output.** The rules state commercial positions ("common market
  standard"), never statute numbers, unless a human verifies them.

## Limits (read before trusting it)

- Romanian-law B2B services contracts only; the checklist is 13 rules, not a full legal review.
- Heuristic clause segmentation: unusual numbering (Roman numerals, `§`) collapses into one unit.
- No OCR: a scanned PDF yields nothing, because `.pdf` extraction needs a text layer.
- Natural-person names are not redacted (company names, CUI, Reg. Com., IBAN, e-mail, phone, address are).
- Output is a triage memo, **not legal advice**; a lawyer signs off.

## Where AutoClaw fits

See `skill/SKILL.md`: the deterministic core runs as a step, the findings feed the legal model
for strategy and redlines, and the memo is the deliverable the user reads. That split keeps the
model's job where it is strong (judgement, drafting) and the rule engine's job where it is
strong (finding and quoting exactly).

## Roadmap

1. Rule pack as data (YAML) so a firm can load its own checklist.
2. PDF catalogue of red flags for public procurement (Legea 98/2016) — needs verified citations first.
3. Diff mode: compare a counterparty's redline against our position set.
