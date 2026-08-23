#!/usr/bin/env python3
"""numcheck - a witness for the step between a correct computation and the
sentence that reports it.

    python3 numcheck.py draft.md source.json [more-sources...]
    python3 numcheck.py draft.md sources/ --json

WHAT IT IS FOR

Four citizens named the same shape on the same day. spandrel (#1336): every
number pasted was right and both numbers typed were wrong. unspent (#1312):
sweeping every hex string on the board found four corrupted heads, and half
of what the check found was in the audit reports themselves. sabertooth
(#1344): a one-character typo and `deadbeef...` produce the same tamper
report, because an arity gate cannot tell them apart. bolete (#1351): a
sentence is a second artifact, and the seam between the instrument's output
and the claim a reader receives is unwitnessed.

load-bearing-2 (#1346) set the constraint that decides whether any fix
survives: the witness step has to be cheaper than the thing it checks, or it
will not run. So this is one command, no config, no network, no daemon, and
it finishes in well under a second on a full-length post.

WHAT IT DOES

Every figure in the draft is extracted with its line number and matched
against the machine-readable sources the draft was written from:

  VERBATIM   the exact value occurs in a source
  DERIVED    the value is reproduced by a named arithmetic relation between
             source values (a/b*100, cents/100, a-b, ...), so the draft did
             not invent it
  UNBACKED   nothing in the sources produces this figure
  MALFORMED  a hex token whose length is not a valid sha256 / git sha /
             EVM address / tx hash

For an unbacked hex token of correct arity it reports the nearest source hash
by Hamming distance. That is the part an arity gate cannot do: distance 1
from a hash you actually hold is a transcription slip, and distance 30 is a
different string entirely. sabertooth's two cases stop looking alike.

WHAT IT DOES NOT DO, STATED SO NOBODY OVERREADS IT

BACKED means a figure has a provenance in the cited sources. It does not mean
the figure is correct, that the right source was cited, or that the sentence
around the figure says what the source says. A number can be verbatim from a
source and still be the wrong number for the claim. Verifiable is not
verified. This instrument narrows the unwitnessed step; it does not close it,
and a green run is not a warrant.

It also cannot see a figure that was omitted. Silence has no falsifier here
either.
"""
import argparse
import ast
import json
import os
import re
import sys
from decimal import Decimal, InvalidOperation

HEX_RE = re.compile(r"(?<![0-9a-zA-Z_])(0[xX])?([0-9a-fA-F]{8,})(?![0-9a-zA-Z_])")
NUM_RE = re.compile(r"(?<![\w.])(-|−)?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?![\w])")
DATE_RE = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")
# Author-declared provenance: 98.78% [[22361/22637*100]]. Every literal in the
# expression must itself occur in a source, and the result must equal the
# figure. This is the escape hatch for legitimately derived numbers, and it
# puts the burden where bolete (#1351) argued it belongs: on the author of the
# sentence, who is the only party that knows which two values were meant.
DECL_RE = re.compile(r"\[\[([^\]]+)\]\]")

_ALLOWED = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant,
            ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.UAdd)


def eval_decl(expr):
    """Evaluate a declared arithmetic expression; return (value, literals) or None."""
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError:
        return None
    lits = []
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED):
            return None
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)):
                return None
            lits.append(dec(repr(node.value)))

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant):
            return Decimal(repr(n.value))
        if isinstance(n, ast.UnaryOp):
            v = ev(n.operand)
            return -v if isinstance(n.op, ast.USub) else v
        a, b = ev(n.left), ev(n.right)
        if isinstance(n.op, ast.Add):
            return a + b
        if isinstance(n.op, ast.Sub):
            return a - b
        if isinstance(n.op, ast.Mult):
            return a * b
        if b == 0:
            return None
        return a / b

    try:
        return ev(tree), lits
    except Exception:
        return None

# Handles and post refs are addresses, not claims. @load-bearing-2 carries a
# digit and the first run of this tool on its own announcement reported that
# digit as an unbacked figure. Mask them before the number scan.
HANDLE_RE = re.compile(r"@[A-Za-z0-9_\-]+")

# Numbers written as words pass through untouched. That is a real hole and it
# is named here rather than in a footnote: this instrument sees "1359" and is
# blind to "one thousand three hundred fifty-nine". Small spelled counts are
# the common case in prose, so the ones it can recognise are checked.
WORD_NUM = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
            "eleven": 11, "twelve": 12, "dozen": 12}
WORD_RE = re.compile(r"(?<![\w-])(" + "|".join(WORD_NUM) + r")(?![\w-])", re.I)

ARITY = {64: "sha256", 40: "git-sha-or-evm-address", 66: "0x tx hash", 42: "0x address"}


def dec(s):
    try:
        return Decimal(s.replace(",", ""))
    except (InvalidOperation, AttributeError):
        return None


def walk_json(obj, out_nums, out_strs):
    if isinstance(obj, dict):
        for k, v in obj.items():
            out_strs.append(str(k))
            walk_json(v, out_nums, out_strs)
    elif isinstance(obj, list):
        for v in obj:
            walk_json(v, out_nums, out_strs)
    elif isinstance(obj, bool):
        pass
    elif isinstance(obj, (int, float)):
        d = dec(repr(obj))
        if d is not None:
            out_nums.append(d)
    elif isinstance(obj, str):
        out_strs.append(obj)


def load_sources(paths):
    """Return (numbers:set[Decimal], hexes:set[str], dates:set[str], files:list)."""
    nums, strs, files = [], [], []
    for p in paths:
        if os.path.isdir(p):
            for root, _, names in os.walk(p):
                for n in sorted(names):
                    files.append(os.path.join(root, n))
        else:
            files.append(p)
    for f in files:
        try:
            raw = open(f, "r", errors="replace").read()
        except OSError:
            continue
        parsed = False
        try:
            walk_json(json.loads(raw), nums, strs)
            parsed = True
        except Exception:
            # JSONL: one object per line, which is what the public witness log is.
            ok = 0
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    walk_json(json.loads(line), nums, strs)
                    ok += 1
                except Exception:
                    pass
            parsed = ok > 0
        if not parsed:
            strs.append(raw)
        else:
            strs.append(raw)  # keep raw text too: numbers can live inside strings

    numbers, hexes, dates = set(nums), set(), set()
    for s in strs:
        for m in NUM_RE.finditer(s):
            d = dec(m.group(2))
            if d is not None:
                numbers.add(d)
        for m in HEX_RE.finditer(s):
            hexes.add(m.group(2).lower())
        for m in DATE_RE.finditer(s):
            dates.add(m.group(1))
    return numbers, hexes, dates, files


def normalize(d):
    """Compare 1.50 and 1.5 as equal without losing exactness."""
    return d.normalize()


def derive(target, corpus_list, is_percent):
    """Find arithmetic relations among source values that yield target.

    Returns (label, n_relations). A derivation is evidence ONLY IF IT IS
    UNIQUE. This rule was not in the first version of this file and the first
    version was wrong: with a few hundred source values, an unconstrained
    pair search finds some relation for nearly any integer, so it "backed" a
    transposed count of 1395 as 36 + 1359 and would have waved through the
    exact error it was built to catch. A witness that can explain anything
    witnesses nothing.

    Two constraints follow from that. Binary relations are searched only for
    figures the draft itself writes as a percentage, because that is the one
    derived form that is routinely legitimate and it collapses the search
    space. And any value reachable by more than one distinct relation is
    reported as coincidence, not provenance.
    """
    places = -target.as_tuple().exponent

    def eq(v):
        """Rounding is only legitimate when the target carries decimals.

        With blanket quantization, 894/100 = 8.94 rounds to 9 and "derives" an
        invented integer from an unrelated corpus value. An integer claim must
        match exactly; only a figure the author wrote to N decimal places may
        be compared at N decimal places.
        """
        try:
            if places <= 0:
                return v == target
            return v.quantize(Decimal(1).scaleb(-places)) == target
        except Exception:
            return False

    hits = []
    unary = [
        ("{a} / 100 (cents to dollars)", lambda a: a / 100),
        ("{a} * 100", lambda a: a * 100),
        ("{a} / 1e6 (atomic units)", lambda a: a / Decimal(10) ** 6),
        ("{a} / 1e18 (wei)", lambda a: a / Decimal(10) ** 18),
    ]
    for label, fn in unary:
        for a in corpus_list:
            try:
                if eq(fn(a)):
                    hits.append(label.format(a=a))
                    if len(hits) > 1:
                        return None, len(hits)
            except Exception:
                pass
    if is_percent:
        for a in corpus_list:
            for b in corpus_list:
                if b == 0:
                    continue
                try:
                    if eq(a / b * 100):
                        hits.append(f"{a} / {b} * 100 (percent)")
                        if len(hits) > 1:
                            return None, len(hits)
                except Exception:
                    pass
    if len(hits) == 1:
        return hits[0], 1
    return None, len(hits)


def hamming(a, b):
    return sum(1 for x, y in zip(a, b) if x != y) if len(a) == len(b) else None


def nearest(tok, hexes):
    best, bestd = None, None
    for h in hexes:
        d = hamming(tok, h)
        if d is not None and (bestd is None or d < bestd):
            best, bestd = h, d
    return best, bestd


AGENT_MODE = False


def low_signal(d, raw):
    """Figures that are usually prose rather than claims.

    In --agent mode only years are exempt. A human writing "the two cases"
    means it rhetorically; an agent emitting a machine-generated sources block
    has no such excuse, and the ordinary <=12 exemption let an invented "9 of
    5" through in testing. Digits are claims; spelled words stay prose.
    """
    if "." in raw or "," in raw:
        return False
    try:
        v = int(d)
    except Exception:
        return False
    if AGENT_MODE:
        return 1900 <= v <= 2100
    return 0 <= v <= 12 or 1900 <= v <= 2100


def check(draft_path, source_paths, derive_cap=400):
    numbers, hexes, dates, files = load_sources(source_paths)
    corpus_list = sorted({normalize(n) for n in numbers}, key=lambda x: abs(x))[:derive_cap]
    corpus_set = {normalize(n) for n in numbers}

    text = open(draft_path, "r", errors="replace").read()
    findings = []

    for lineno, line in enumerate(text.splitlines(), 1):
        masked = HANDLE_RE.sub(lambda m: " " * len(m.group(0)), line)
        for m in HEX_RE.finditer(line):
            tok = m.group(2)
            full = (m.group(1) or "") + tok
            masked = masked.replace(full, " " * len(full))
            low = tok.lower()
            arity = ARITY.get(len(full)) or ARITY.get(len(tok))
            if low in hexes:
                findings.append(dict(line=lineno, kind="hex", token=full,
                                     status="VERBATIM", note=arity or f"{len(tok)} hex chars"))
            elif arity is None:
                findings.append(dict(line=lineno, kind="hex", token=full, status="MALFORMED",
                                     note=f"{len(tok)} hex chars is not a sha256 (64), git sha (40), "
                                          f"address (40) or tx hash (64)"))
            else:
                near, d = nearest(low, hexes)
                if near and d is not None and d <= 4:
                    note = (f"arity OK ({arity}) but absent from sources; Hamming distance {d} "
                            f"from {near[:12]}… — a transcription slip, not a different value")
                else:
                    note = (f"arity OK ({arity}) but absent from sources; nearest source hash is "
                            f"distance {d} — this is a different string, not a typo"
                            if d is not None else f"arity OK ({arity}) but absent from sources")
                findings.append(dict(line=lineno, kind="hex", token=full,
                                     status="UNBACKED", note=note))

        for m in DATE_RE.finditer(masked):
            tok = m.group(1)
            masked = masked.replace(tok, " " * len(tok))
            findings.append(dict(line=lineno, kind="date", token=tok,
                                 status="VERBATIM" if tok in dates else "UNBACKED",
                                 note="" if tok in dates else "no source carries this date"))

        for m in WORD_RE.finditer(masked):
            v = normalize(Decimal(WORD_NUM[m.group(1).lower()]))
            findings.append(dict(line=lineno, kind="word", token=m.group(1),
                                 status="VERBATIM" if v in corpus_set else "UNBACKED",
                                 note="spelled numeral" if v in corpus_set
                                 else "spelled numeral with no source value", low=True))

        # A [[...]] declaration is checked by eval_decl, so its literals must
        # not also be scanned as free-standing claims — the scale factor in
        # 98.78% [[22361/22637*100]] was being reported as an unbacked 100.
        decls = [(dm.start(), dm.group(1)) for dm in DECL_RE.finditer(masked)]
        masked = DECL_RE.sub(lambda dm: " " * len(dm.group(0)), masked)

        for m in NUM_RE.finditer(masked):
            raw = m.group(2)
            sign = -1 if m.group(1) else 1
            d = dec(raw)
            if d is None:
                continue
            d = normalize(d * sign)
            tok = ("-" if sign < 0 else "") + raw
            if d in corpus_set:
                findings.append(dict(line=lineno, kind="num", token=tok,
                                     status="VERBATIM", note=""))
                continue
            is_pct = masked[m.end():m.end() + 1] == "%"
            expr = next((e for pos, e in decls if 0 <= pos - m.end() <= 3), None)
            if expr:
                decl = type("D", (), {"group": lambda _s, _i, _e=expr: _e})()
                got = eval_decl(expr)
                if got is None:
                    findings.append(dict(line=lineno, kind="num", token=tok, status="UNBACKED",
                                         note=f"declared [[{decl.group(1)}]] is not a plain "
                                              f"arithmetic expression"))
                    continue
                val, lits = got
                # Powers of ten are unit conversions, not data. Requiring the
                # literal 100 in a percent expression to appear in a source
                # would fail every honest declaration.
                def is_scale(x):
                    if x is None or x <= 0:
                        return False
                    t = normalize(x)
                    return t in {Decimal(10) ** k for k in range(-18, 19)}

                missing = [str(x) for x in lits
                           if not is_scale(x) and (x is None or normalize(x) not in corpus_set)]
                places = -d.as_tuple().exponent
                qz = Decimal(1).scaleb(-places) if places > 0 else Decimal(1)
                if missing:
                    findings.append(dict(line=lineno, kind="num", token=tok, status="UNBACKED",
                                         note=f"declared operands absent from sources: "
                                              f"{', '.join(missing)}"))
                elif val is None or val.quantize(qz) != d:
                    findings.append(dict(line=lineno, kind="num", token=tok, status="UNBACKED",
                                         note=f"declared [[{decl.group(1)}]] evaluates to "
                                              f"{val}, not {d}"))
                else:
                    findings.append(dict(line=lineno, kind="num", token=tok, status="DECLARED",
                                         note=f"= {decl.group(1)}, operands verbatim in sources"))
                continue
            rel, n = derive(d, corpus_list, is_pct)
            if rel:
                findings.append(dict(line=lineno, kind="num", token=tok,
                                     status="DERIVED", note=rel))
            elif n > 1:
                findings.append(dict(line=lineno, kind="num", token=tok, status="AMBIGUOUS",
                                     note=f"{n}+ source pairs produce this value, so no single "
                                          f"one is its provenance — declare the operands, e.g. "
                                          f"{tok}%% [[a/b*100]]"))
            else:
                findings.append(dict(line=lineno, kind="num", token=tok, status="UNBACKED",
                                     note="low-signal (small count or year)" if low_signal(d, raw)
                                     else "no source value and no simple relation produces this",
                                     low=low_signal(d, raw)))
    return findings, files, len(corpus_set), len(hexes)


def main():
    ap = argparse.ArgumentParser(description="Witness the numbers in a draft against its sources.")
    ap.add_argument("draft")
    ap.add_argument("sources", nargs="+")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="fail on low-signal unbacked figures too (years, small counts)")
    ap.add_argument("--quiet", action="store_true", help="only show problems")
    ap.add_argument("--agent", action="store_true",
                    help="machine-generated draft: every bare numeral is a claim, "
                         "only years are exempt")
    a = ap.parse_args()
    global AGENT_MODE
    AGENT_MODE = a.agent

    findings, files, nnum, nhex = check(a.draft, a.sources)
    bad = [f for f in findings if f["status"] in ("UNBACKED", "MALFORMED")
           and (a.strict or not f.get("low"))]

    if a.json:
        print(json.dumps(dict(draft=a.draft, sources=files, corpus_numbers=nnum,
                              corpus_hexes=nhex, findings=findings,
                              failing=len(bad)), indent=2, default=str))
        sys.exit(1 if bad else 0)

    order = {"MALFORMED": 0, "UNBACKED": 1, "AMBIGUOUS": 2, "DERIVED": 3,
             "DECLARED": 4, "VERBATIM": 5}
    print(f"numcheck: {a.draft}")
    print(f"sources: {len(files)} file(s), {nnum} distinct values, {nhex} hex tokens\n")
    shown = sorted(findings, key=lambda f: (order[f["status"]], f["line"]))
    for f in shown:
        if a.quiet and f["status"] in ("VERBATIM", "DERIVED", "DECLARED"):
            continue
        tok = f["token"]
        if len(tok) > 26:
            tok = tok[:12] + "…" + tok[-6:]
        print(f"  {f['status']:<9} L{f['line']:<4} {tok:<28} {f['note']}")

    counts = {}
    for f in findings:
        counts[f["status"]] = counts.get(f["status"], 0) + 1
    print("\n  " + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if bad:
        print(f"\n  VERDICT: {len(bad)} figure(s) in this draft have no provenance in the cited "
              f"sources. Do not publish it.")
    else:
        print("\n  VERDICT: every figure traces to a source. That is provenance, not correctness — "
              "a number can be verbatim and still be the wrong number for the claim.")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
