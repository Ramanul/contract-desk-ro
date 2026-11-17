---
name: contract-desk-ro
description: Review a Romanian-law contract (docx/pdf/txt) and produce a risk memo, a triage spreadsheet and an anonymised copy. Use when the user shares a contract and asks what is risky, what to negotiate, or needs a copy safe to send to a third party.
---

# Contract Desk (RO)

Deterministic first pass on a contract, then judgement on top of it.

## When to use

- "What is risky in this contract?", "ce clauze sunt problematice?", "ce negociez?"
- "Anonimizează contractul ca să-l pot trimite" (redacted copy for external sharing)
- Triage before a lawyer reads it: which clauses deserve attention first

## Steps

1. **Find the file.** Ask for the path if the user pasted text only; a pasted contract can be
   saved as `.txt` and still works.
2. **Run the engine** (path relative to this skill):
   ```
   python src/ro_contract_review.py --input <contract> --out out/<contract-name>
   ```
   It prints the finding list; keep those numbers, they go into the answer verbatim.
3. **Read the memo** (`out/<name>/review_memo.docx`) and `findings.json`. Do not re-derive the
   findings by reading the contract yourself — the engine's quotes are exact and the rule IDs are
   stable references.
4. **Add judgement, not repetition.** For the high-severity findings only, say what to ask for in
   the negotiation and what a fallback position looks like. Do not invent statute numbers or case
   law; if a legal citation is needed, say it must be verified by counsel.
5. **Deliver**: memo + spreadsheet as files, redacted copy only if the user asked for it. Never
   deliver `redaction_map.json` alongside the redacted document.

## Rules

- Never claim a clause is "illegal" — the engine reports commercial risk, not nullity.
- If the document is a scanned PDF (no text layer), say so and stop; there is no OCR here.
- Keep the rule IDs (R01…R13) in the answer so the user can trace each point back to the file.
