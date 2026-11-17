#!/usr/bin/env python3
"""RO Contract Review - deterministic first pass over a Romanian-law contract.

Pipeline: extract text -> segment clauses -> apply risk rule pack -> render artifacts.
Outputs (in --out): findings.json, findings.xlsx, review_memo.docx, redacted_contract.docx,
redaction_map.json.

Design note: the rule layer is deterministic and offline on purpose (auditable, no
hallucinated citations). The judgement layer - negotiating strategy, clause rewriting
in context - is delegated to the legal model inside AutoClaw.

Usage:
    python src/ro_contract_review.py --input data/sample_contract.docx --out out
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------- text handling

_TABLE = str.maketrans({
    "ă": "a", "â": "a", "î": "i", "ș": "s", "ş": "s", "ț": "t", "ţ": "t",
    "Ă": "a", "Â": "a", "Î": "i", "Ș": "s", "Ş": "s", "Ț": "t", "Ţ": "t",
})


def norm(text: str) -> str:
    """Lowercase + strip Romanian diacritics, preserving string length 1:1.

    Length preservation matters: match offsets in the normalized string map back to
    the original string, so evidence quotes slice correctly.
    """
    return text.translate(_TABLE).lower()


def utf8_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        import docx

        document = docx.Document(str(path))
        parts = [p.text for p in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text for cell in row.cells))
        return "\n".join(parts)
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    return path.read_text(encoding="utf-8", errors="replace")


_ART = re.compile(r"^\s*art(?:icolul)?\.?\s*(?P<num>\d+)\s*[\.\)]?\s*", re.I)
_DOTTED = re.compile(r"^\s*(?P<num>\d+(?:\.\d+)+)\s+")
_SIMPLE = re.compile(r"^\s*(?P<num>\d+)\s*[\.\)]\s+")


def clause_id(line: str) -> str | None:
    """Return a clause id when the line opens a new clause, else None.

    Order matters: '12.1 Text' must be read as 12.1 (dotted), not as 12 followed by '.1'.
    """
    for regex in (_ART, _DOTTED, _SIMPLE):
        match = regex.match(line)
        if match:
            return match.group("num")
    return None


def segment(text: str) -> list[dict]:
    clauses: list[dict] = []
    current: dict | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        cid = clause_id(line)
        if cid:
            current = {"id": cid, "heading": line[:120], "body": line + "\n"}
            clauses.append(current)
        elif current is None:
            current = {"id": "preamble", "heading": line[:120], "body": line + "\n"}
            clauses.append(current)
        else:
            current["body"] += line + "\n"
            if len(line) < 90 and line.isupper():
                current["heading"] = line[:120]
    return clauses if len(clauses) >= 3 else [{"id": "DOC", "heading": "(document)", "body": text}]


# -------------------------------------------------------------------- rule pack

def _has_cap(text: str) -> bool:
    """True when a liability cap actually exists ('nelimitat' is not a cap)."""
    cleaned = text.replace("nelimitat", " ")
    return bool(re.search(r"plafon|pana la|nu (?:va )?depasi|limitat\w* la|maximum", cleaned))


def _no_termination(text: str) -> bool:
    return not re.search(r"(denunt|rezili|incet)\w*[^.]{0,120}(fara motiv|oricand|preaviz)", text)


def _no_notice_channel(text: str) -> bool:
    return "notificar" in text and not re.search(
        r"notificar\w*[^.]{0,120}(e-?mail|adresa de e-mail|scrisoare|posta|curier)", text
    )


# Patterns are matched against normalized text, so they are written without diacritics.
RULES: list[dict] = [
    {
        "id": "R01",
        "title": "Lipsa plafonului de răspundere",
        "severity": "high",
        "scope": "doc",
        "check": lambda t: ("raspundere" in t) and not _has_cap(t),
        "why": "Fără plafon (de regulă valoarea contractului sau 12 luni de onorariu), expunerea este "
               "nelimitată și imposibil de asigurat. Un plafon este standard de piață, nu o concesiune.",
        "fix": "Adaugă: „Răspunderea fiecărei părți este limitată la valoarea totală a contractului, "
               "cu excepția dolului și a culpei grave.”",
    },
    {
        "id": "R02",
        "title": "Răspundere nelimitată / daune nelimitate",
        "severity": "high",
        "scope": "clause",
        "patterns": [r"raspundere[^.]{0,120}nelimitat", r"nelimitat[^.]{0,60}(raspundere|daune|despagubir)",
                     r"toate daunele", r"inclusiv pierderea de profit"],
        "guards": [r"cu exceptia", r"(?<!ne)limitat\w*"],
        "why": "Sunt incluse daunele indirecte și pierderea de profit fără plafon: o singură întrerupere "
               "poate depăși de multe ori valoarea contractului.",
        "fix": "Elimină daunele indirecte și pierderea de profit; păstrează daunele directe, plafonate.",
    },
    {
        "id": "R03",
        "title": "Prelungire automată fără preaviz",
        "severity": "medium",
        "scope": "clause",
        "patterns": [r"(se )?(prelungeste|reinnoieste) automat", r"prelungire automata",
                     r"fara notificare prealabila"],
        "guards": [r"preaviz", r"notificare scrisa cu \d+ zile"],
        "why": "Te leagă pe termen nelimitat fără să observi: bugetul anului viitor este angajat tacit.",
        "fix": "Prelungire doar prin act adițional sau cu preaviz scris de 30-60 de zile.",
    },
    {
        "id": "R04",
        "title": "Modificare unilaterală a contractului",
        "severity": "high",
        "scope": "clause",
        "patterns": [r"modific\w* unilateral", r"unilateral\w*[^.]{0,80}(tarif|pret|modific)",
                     r"fara acordul scris"],
        "guards": [r"prin acord scris"],
        "why": "Prețul și sfera serviciilor devin modificabile de o singură parte: contractul își pierde "
               "valoarea de instrument de control al costurilor.",
        "fix": "Orice modificare prin act adițional semnat de ambele părți.",
    },
    {
        "id": "R05",
        "title": "Termen de plată peste 60 de zile",
        "severity": "medium",
        "scope": "clause",
        "patterns": [r"termen de plata[^.;]{0,80}?(\d{2,3})\s*(?:de\s*)?zile",
                     r"(?:in )?termen de (\d{2,3})\s*(?:de\s*)?zile"],
        "value_test": lambda v: v > 60,
        "why": "Peste 60 de zile rar se justifică între profesioniști; finanțezi practic clientul și "
               "crești riscul de neîncasare.",
        "fix": "Negociază 30 de zile, maximum 45; leagă plata de acceptarea procesului-verbal.",
    },
    {
        "id": "R06",
        "title": "Penalități de întârziere disproporționat de mari",
        "severity": "medium",
        "scope": "clause",
        "patterns": [r"penalitat\w*[^.;]{0,80}?(\d+(?:[.,]\d+)?)\s*%"],
        "value_test": lambda v: v > 0.5,
        "why": "Peste ~0,5%/zi se ajunge la 180%/an; instanța poate reduce, dar până atunci este pârghie "
               "de presiune.",
        "fix": "Plafonează penalitățile la 0,1%/zi și la maximum 10% din valoarea facturii.",
    },
    {
        "id": "R07",
        "title": "Lipsa dreptului de denunțare unilaterală",
        "severity": "medium",
        "scope": "doc",
        "check": _no_termination,
        "why": "Fără clauză de denunțare cu preaviz, ieșirea din contract presupune acordul celeilalte "
               "părți sau o acțiune în instanță.",
        "fix": "Adaugă denunțare cu preaviz scris de 30 de zile, fără penalități.",
    },
    {
        "id": "R08",
        "title": "Instanțe / lege străină",
        "severity": "high",
        "scope": "clause",
        "patterns": [r"legislatia (engleza|statului new york|elvetiana|franceza|germana)",
                     r"instantele? (competente )?din (?!bucuresti|cluj|romania|tribunalul)",
                     r"arbitraj\w*[^.]{0,60}(londra|paris|viena|zurich)"],
        "why": "Costul unui litigiu la Londra depășește de regulă valoarea contractului; protecția legală "
               "devine teoretică.",
        "fix": "Lege română, instanțele de la sediul pârâtului, sau arbitraj la Curtea de Arbitraj "
               "Comercială București.",
    },
    {
        "id": "R09",
        "title": "Cesiune de proprietate intelectuală peste limita livrabilelor",
        "severity": "medium",
        "scope": "clause",
        "patterns": [r"creatii viitoare", r"inclusiv (?:creatii|oper[ae]) viitoare"],
        "why": "Cesiunea creațiilor viitoare nu poate fi cuantificată la semnare și poate acoperi know-how "
               "care nu are legătură cu proiectul.",
        "fix": "Limitează cesiunea la livrabilele enumerate în anexă, la plata integrală.",
    },
    {
        "id": "R10",
        "title": "Date cu caracter personal fără acord de prelucrare",
        "severity": "high",
        "scope": "clause",
        "patterns": [r"date cu caracter personal"],
        "guards": [r"imputernicit", r"acord de prelucrare", r"2016/679", r"\bgdpr\b", r"\bdpa\b"],
        "why": "Dacă se prelucrează date în numele celeilalte părți, lipsa contractului de împuternicit "
               "expune ambele părți la risc de sancțiune.",
        "fix": "Anexează acordul de prelucrare (art. 28 GDPR) cu scop, durată și categorii de date.",
    },
    {
        "id": "R11",
        "title": "Confidențialitate pe durată nelimitată",
        "severity": "low",
        "scope": "clause",
        "patterns": [r"confidentialitate[^.]{0,100}(nelimitat|permanent|fara limita)"],
        "why": "Obligație veșnică, greu de administrat și de dovedit; durata standard este de 2-5 ani "
               "după încetare.",
        "fix": "Durată de 3 ani după încetare, cu excepții pentru informații publice și cerințe legale.",
    },
    {
        "id": "R12",
        "title": "Cesiune de contract fără acordul celeilalte părți",
        "severity": "medium",
        "scope": "clause",
        "patterns": [r"cesion\w*[^.]{0,100}fara acordul", r"poate cesiona"],
        "why": "Partenerul contractat poate fi înlocuit cu un terț necunoscut, inclusiv un concurent.",
        "fix": "Cesiune permisă numai cu acordul scris prealabil al celeilalte părți.",
    },
    {
        "id": "R13",
        "title": "Canal de notificări nedefinit",
        "severity": "low",
        "scope": "doc",
        "check": _no_notice_channel,
        "why": "Fără adresă de e-mail și termen de răspuns, notificările se pot pierde; afectează aplicarea "
               "preavizelor și a penalităților.",
        "fix": "Definește persoana de contact, adresa de e-mail și regula de confirmare în 3 zile lucrătoare.",
    },
]

SEV_ORDER = {"high": 0, "medium": 1, "low": 2}
SEV_LABEL = {"high": "RIDICAT", "medium": "MEDIU", "low": "SCĂZUT"}
SEV_LOWER = {"high": "ridicată", "medium": "medie", "low": "scăzută"}


# --------------------------------------------------------------------- analysis

def _finding(rule: dict, clause: str, source: str, pos: int) -> dict:
    if clause == "document":
        quote = "(clauză absentă din document)"
    else:
        start = max(0, pos - 70)
        quote = re.sub(r"\s+", " ", source[start:pos + 150]).strip()
    return {
        "rule": rule["id"],
        "title": rule["title"],
        "severity": rule["severity"],
        "clause": clause,
        "quote": quote,
        "why": rule["why"],
        "fix": rule["fix"],
    }


def analyze(text: str, clauses: list[dict]) -> list[dict]:
    findings: list[dict] = []
    full_norm = norm(text)

    for rule in RULES:
        if rule.get("scope") == "doc":
            if rule["check"](full_norm):
                findings.append(_finding(rule, "document", text, 0))
            continue

        for clause in clauses:
            body_norm = norm(clause["body"])
            if any(re.search(guard, body_norm) for guard in rule.get("guards", [])):
                continue
            for pattern in rule["patterns"]:
                match = re.search(pattern, body_norm)
                if not match:
                    continue
                test = rule.get("value_test")
                if test is not None:
                    try:
                        value = float(match.group(1).replace(",", "."))
                    except (IndexError, ValueError):
                        continue
                    if not test(value):
                        continue
                findings.append(_finding(rule, clause["id"], clause["body"], match.start()))
                break

    # One finding per (rule, article): 12.1 and 12.2 are the same negotiation issue.
    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for finding in findings:
        key = (finding["rule"], finding["clause"].split(".")[0])
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)

    unique.sort(key=lambda f: (SEV_ORDER[f["severity"]], f["rule"], f["clause"]))
    return unique


# -------------------------------------------------------------------- redaction

REDACT_PATTERNS = [
    ("COMPANIE", re.compile(r"\bS\.?\s?C\.?\s+[A-ZĂÂÎȘȚ][\w&.\-]*(?:\s+[A-ZĂÂÎȘȚ][\w&.\-]*)*\s+(?:S\.?R\.?L\.?|S\.?A\.?|S\.?N\.?C\.?)\.?")),
    ("CUI", re.compile(r"\b(?:CUI|C\.U\.I\.|CIF)\s*(?:RO)?\s?\d{6,10}\b")),
    ("REG_COM", re.compile(r"\bJ\d{2}/\d{2,6}/\d{4}\b")),
    ("IBAN", re.compile(r"\bRO\d{2}[A-Z]{4}[A-Z0-9]{16}\b")),
    ("EMAIL", re.compile(r"\b[\w.\-]+@[\w.\-]+\.\w{2,}\b")),
    ("TELEFON", re.compile(r"(?:\+40|0)\s?7\d{2}[\s.\-]?\d{3}[\s.\-]?\d{3}\b")),
    ("ADRESA", re.compile(r"\b(?:Str\.|Strada|Bd\.|Bulevardul|Calea|Aleea)\s+[A-ZĂÂÎȘȚ][^,;.]{2,40}(?:nr\.\s?\d+[A-Za-z]?)")),
]


def redact(text: str) -> tuple[str, dict[str, str]]:
    mapping: dict[str, str] = {}
    counters: dict[str, int] = {}
    redacted = text

    for label, pattern in REDACT_PATTERNS:
        def repl(match: re.Match, label: str = label) -> str:
            original = match.group(0)
            if original in mapping:
                return mapping[original]
            counters[label] = counters.get(label, 0) + 1
            placeholder = f"[{label}_{counters[label]}]"
            mapping[original] = placeholder
            return placeholder

        redacted = pattern.sub(repl, redacted)

    return redacted, mapping


# ---------------------------------------------------------------------- writers

def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_xlsx(path: Path, findings: list[dict]) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    summary = wb.active
    summary.title = "Summary"
    summary["A1"] = "Constatări pe severitate"
    summary["A1"].font = Font(bold=True, size=13)
    summary["A3"], summary["B3"] = "Severitate", "Număr"
    for cell in (summary["A3"], summary["B3"]):
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="333333")
    row = 4
    for severity in ("high", "medium", "low"):
        summary[f"A{row}"] = SEV_LABEL[severity]
        summary[f"B{row}"] = sum(1 for f in findings if f["severity"] == severity)
        row += 1
    summary[f"A{row}"] = "TOTAL"
    summary[f"B{row}"] = len(findings)
    summary[f"A{row}"].font = Font(bold=True)
    summary[f"B{row}"].font = Font(bold=True)
    summary.column_dimensions["A"].width = 26
    summary.column_dimensions["B"].width = 10

    sheet = wb.create_sheet("Findings")
    headers = ["#", "Regulă", "Constatare", "Severitate", "Clauză", "Citat", "De ce contează", "Recomandare"]
    sheet.append(headers)
    for index, header in enumerate(headers, start=1):
        cell = sheet.cell(row=1, column=index)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F3864")
        cell.alignment = Alignment(vertical="center")

    fills = {"high": "FFC7CE", "medium": "FFEB9C", "low": "E7E6E6"}
    for index, finding in enumerate(findings, start=1):
        sheet.append([
            index, finding["rule"], finding["title"], SEV_LABEL[finding["severity"]],
            finding["clause"], finding["quote"], finding["why"], finding["fix"],
        ])
        sheet.cell(row=index + 1, column=4).fill = PatternFill("solid", fgColor=fills[finding["severity"]])
        for column in (6, 7, 8):
            sheet.cell(row=index + 1, column=column).alignment = Alignment(wrap_text=True, vertical="top")
        sheet.row_dimensions[index + 1].height = 64

    widths = [5, 9, 38, 12, 12, 48, 52, 48]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:H{len(findings) + 1}"

    wb.save(str(path))


def write_memo(path: Path, source: Path, clauses: list[dict], findings: list[dict]) -> None:
    import docx
    from docx.shared import Pt, RGBColor

    document = docx.Document()
    document.add_heading("Memorandum de revizuire contractuală", level=0)
    meta = document.add_paragraph()
    meta.add_run(f"Document analizat: {source.name}\n").bold = True
    meta.add_run(f"Data analizei: {date.today().isoformat()}\n")
    meta.add_run(f"Clauze identificate: {len(clauses)}\n")
    meta.add_run(f"Constatări: {len(findings)}")

    document.add_heading("1. Sinteză", level=1)
    counts = {severity: sum(1 for f in findings if f["severity"] == severity) for severity in SEV_ORDER}
    document.add_paragraph(
        f"Revizuirea automată a identificat {len(findings)} puncte de risc: "
        f"{counts['high']} cu severitate ridicată, {counts['medium']} medie, {counts['low']} scăzută. "
        "Punctele marcate ridicat se tratează înainte de semnare; cele medii sunt obiect de negociere."
    )

    document.add_heading("2. Constatări detaliate", level=1)
    for index, finding in enumerate(findings, start=1):
        heading = document.add_heading(level=2)
        run = heading.add_run(f"{index}. {finding['title']}")
        run.font.size = Pt(12)
        tag = document.add_paragraph()
        tag_run = tag.add_run(
            f"{finding['rule']} · severitate {SEV_LOWER[finding['severity']]} · "
            f"{'la nivel de document' if finding['clause'] == 'document' else 'clauza ' + finding['clause']}"
        )
        tag_run.italic = True
        tag_run.font.size = Pt(9)
        tag_run.font.color.rgb = RGBColor(0x59, 0x59, 0x59)

        quote = document.add_paragraph()
        quote.paragraph_format.left_indent = Pt(14)
        quote_run = quote.add_run(f"„{finding['quote']}”")
        quote_run.italic = True

        why = document.add_paragraph()
        why.add_run("De ce contează: ").bold = True
        why.add_run(finding["why"])

        fix = document.add_paragraph()
        fix.add_run("Recomandare: ").bold = True
        fix.add_run(finding["fix"])

    document.add_heading("3. Limite și pas următor", level=1)
    document.add_paragraph(
        "Analiza este un triaj determinist pe un set de reguli pentru drept românesc; nu înlocuiește avizul "
        "unui avocat și nu acoperă clauzele specifice sectorului. Pas următor: negocierea punctelor marcate "
        "ridicat și redactarea contra-propunerilor."
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(path))


def write_redacted(path: Path, source: Path, mapping: dict[str, str]) -> None:
    import docx

    target = docx.Document()
    if source.suffix.lower() == ".docx":
        original = docx.Document(str(source))
        for paragraph in original.paragraphs:
            text = paragraph.text
            for key, value in mapping.items():
                text = text.replace(key, value)
            style = paragraph.style.name if paragraph.style else ""
            if style.startswith("Heading") and style[-1].isdigit():
                target.add_heading(text, level=int(style[-1]))
            else:
                target.add_paragraph(text)
    else:
        text = source.read_text(encoding="utf-8", errors="replace")
        for key, value in mapping.items():
            text = text.replace(key, value)
        for line in text.splitlines():
            target.add_paragraph(line)

    path.parent.mkdir(parents=True, exist_ok=True)
    target.save(str(path))


# ------------------------------------------------------------------------- main

def main() -> int:
    utf8_streams()
    parser = argparse.ArgumentParser(description="Deterministic contract review for Romanian-law documents.")
    parser.add_argument("--input", required=True, help="contract file (.docx, .pdf, .txt)")
    parser.add_argument("--out", default="out", help="output directory")
    parser.add_argument("--no-redact", action="store_true", help="skip the redacted copy")
    args = parser.parse_args()

    source = Path(args.input)
    if not source.exists():
        print(f"ERROR: input not found: {source}")
        return 2

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    text = extract_text(source)
    clauses = segment(text)
    findings = analyze(text, clauses)

    write_json(out_dir / "findings.json", {
        "source": str(source),
        "analyzed_on": date.today().isoformat(),
        "clauses": len(clauses),
        "findings_count": len(findings),
        "findings": findings,
    })
    write_xlsx(out_dir / "findings.xlsx", findings)
    write_memo(out_dir / "review_memo.docx", source, clauses, findings)

    if not args.no_redact:
        _, mapping = redact(text)
        write_redacted(out_dir / "redacted_contract.docx", source, mapping)
        write_json(out_dir / "redaction_map.json", mapping)
        print(f"[redact] {len(mapping)} entități înlocuite")

    counts = {severity: sum(1 for f in findings if f["severity"] == severity) for severity in SEV_ORDER}
    print(f"[input]  {source}  ({source.stat().st_size} bytes)")
    print(f"[parse]  {len(text)} caractere, {len(clauses)} clauze")
    print(f"[review] {len(findings)} constatări: ridicat={counts['high']} mediu={counts['medium']} scăzut={counts['low']}")
    for finding in findings:
        print(f"  - {finding['rule']} [{SEV_LABEL[finding['severity']]:>7}] {finding['title']} (clauza {finding['clause']})")
    print(f"[out]    {out_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
