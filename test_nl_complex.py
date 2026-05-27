"""
NL Quality Round 3 — stress-test suite.
Covers: IJ digraph, extended case normalization, Eisen/Rollen/Wielen,
2er-Set, DutchWorkbookConsistencyMemory metadata, hybrid detector,
naturalness rewriter, QA critical extension.

Run:  python3 test_nl_complex.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from nl_engine import (
    normalize_ij_capitalization,
    normalize_dutch_case,
    nl_post_process,
    apply_nl_format_normalization,
    detect_hybrid_language_words,
    nl_naturalness_rewrite,
    nl_qa_check,
    DutchWorkbookConsistencyMemory,
    NL_FURNITURE_CANONICAL,
    NL_FORBIDDEN_REPLACEMENTS,
    _NL_QA_CRITICAL_FORBIDDEN,
)

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
failures = 0


def check(label: str, condition: bool) -> None:
    global failures
    status = PASS if condition else FAIL
    print(f"  [{status}] {label}")
    if not condition:
        failures += 1


# ===========================================================================
# 1. IJ digraph normalization
# ===========================================================================
print("\n=== 1. IJ digraph capitalization ===\n")

check("Ijzer → IJzer", normalize_ij_capitalization("Ijzer") == "IJzer")
check("Ijsland → IJsland", normalize_ij_capitalization("Ijsland") == "IJsland")
check("IJzer already correct — unchanged", normalize_ij_capitalization("IJzer") == "IJzer")
check("ijzer lowercase — unchanged (all-lower is fine)", normalize_ij_capitalization("ijzer") == "ijzer")
check("Nijl (NI not IJ) — unchanged", normalize_ij_capitalization("Nijl") == "Nijl")
check("multiple Ij in sentence", normalize_ij_capitalization("Ijzer en Ijsland") == "IJzer en IJsland")
check("mid-word Ij not touched (e.g. bij)", normalize_ij_capitalization("bij het frame") == "bij het frame")


# ===========================================================================
# 2. Eisen → IJzer via canonical map
# ===========================================================================
print("\n=== 2. Eisen → IJzer (canonical map) ===\n")

result = nl_post_process("Frame van Eisen")
check("Eisen → IJzer", "IJzer" in result)
check("no 'Eisen' residue", "Eisen" not in result)

result = nl_post_process("Eisen frame zwart", "colorDetail")
check("Eisen → IJzer in attribute", "IJzer" in result)

# Forbidden: Ijzer (wrong casing) → IJzer
result = nl_post_process("Frame van Ijzer")
check("Ijzer → IJzer (forbidden replacement)", "IJzer" in result and "Ijzer" not in result)

# Forbidden: IJs (ice) when source was Eisen
result = nl_post_process("Frame IJs kleur")
check("IJs → IJzer (semantic error correction)", "IJzer" in result)


# ===========================================================================
# 3. Rollen → rollen (castors, not vehicle wheels)
# ===========================================================================
print("\n=== 3. Rollen → rollen / Wielen forbidden ===\n")

result = nl_post_process("Stoel met Rollen")
check("Rollen → rollen (lowercase)", "rollen" in result and "Rollen" not in result)

result = nl_post_process("Wielen voor meubels")
check("Wielen → rollen (forbidden)", "rollen" in result and "Wielen" not in result)

issues = nl_qa_check("Stoel met Wielen")
sev = [i["severity"] for i in issues]
check("QA flags Wielen as Critical", "Critical" in sev)

issues = nl_qa_check("stoel met rollen")
wielen_issue = any("Wielen" in i["message"] for i in issues)
check("QA clean for 'rollen' (correct form)", not wielen_issue)


# ===========================================================================
# 4. 2er-Set → set van 2
# ===========================================================================
print("\n=== 4. 2er-Set → set van 2 ===\n")

check("2er-Set → set van 2", apply_nl_format_normalization("2er-Set") == "set van 2")
check("4er-Set → set van 4", "set van 4" in apply_nl_format_normalization("4er-Set meubels"))
check("6er-Set → set van 6", apply_nl_format_normalization("6er-Set") == "set van 6")
check("2er-set (lowercase) → set van 2", apply_nl_format_normalization("2er-set") == "set van 2")
check("no match on 'seter' (not a set)", "seter" in apply_nl_format_normalization("seter"))
check("via nl_post_process: 2er-Set resolved", "set van 2" in nl_post_process("2er-Set stoel"))


# ===========================================================================
# 5. Extended case normalization (/, &, <br>)
# ===========================================================================
print("\n=== 5. Extended case normalization ===\n")

# After slash
check("zwart/Wit → zwart/wit (colorDetail)", normalize_dutch_case("zwart/Wit", "colorDetail") == "zwart/wit")
check("Zwart/Beige → Zwart/beige", normalize_dutch_case("Zwart/Beige", "colorDetail") == "Zwart/beige")
check("LED/Mat — ALL-CAPS not lowercased after /", "LED" in normalize_dutch_case("LED/Mat", "colorDetail"))

# After ampersand
check("Leer & Stof → Leer & stof", normalize_dutch_case("Leer & Stof", "materialDetail") == "Leer & stof")
check("Body & Werkblad → Body & werkblad", normalize_dutch_case("Body & Werkblad", "materialDetail") == "Body & werkblad")

# After <br> — values lowercased, labels not
check("<br>Beige → <br>beige (value)", normalize_dutch_case("zwart<br>Beige", "colorDetail") == "zwart<br>beige")
check("<br>Poten: unchanged (label after br)", normalize_dutch_case("zwart<br>Poten: zwart", "colorDetail") == "zwart<br>Poten: zwart")

# name column skipped
check("name column: not mutated", normalize_dutch_case("Zwart/Wit", "name") == "Zwart/Wit")

# Integration via nl_post_process
r = nl_post_process("Bekleding: Zwart<br>Poten: Zwart", "variantName")
check("Full cell: labels preserved, values lowercased", "Poten: zwart" in r and "Bekleding: zwart" in r)

r = nl_post_process("Schwarz/Weiß", "colorDetail")
check("DE Schwarz/Weiß → nl zwart/wit via pipeline", "zwart" in r.lower() and "wit" in r.lower())


# ===========================================================================
# 6. DutchWorkbookConsistencyMemory — metadata
# ===========================================================================
print("\n=== 6. DutchWorkbookConsistencyMemory metadata ===\n")

mem = DutchWorkbookConsistencyMemory()

# backward-compatible put (no kwargs)
mem.put("Sofa", "bank")
check("put() without kwargs — still works", mem.get("Sofa") == "bank")

# put() with metadata
mem2 = DutchWorkbookConsistencyMemory()
mem2.put("Sofa", "bank", origin="TM", confidence=0.95)
meta = mem2.get_meta("Sofa")
check("get_meta returns dict", isinstance(meta, dict))
check("meta origin is 'TM'", meta["origin"] == "TM")
check("meta confidence is 0.95", meta["confidence"] == 0.95)
check("meta count starts at 1", meta["count"] == 1)

# get() increments count
mem2.get("Sofa")
meta2 = mem2.get_meta("Sofa")
check("get() increments hit count", meta2["count"] == 2)

# first write wins
mem2.put("Sofa", "zetel")
check("second put() does not overwrite", mem2.get("Sofa") == "bank")

# get_or_default with metadata
result = mem2.get_or_default("Tafel", "tafel", origin="glossary", confidence=1.0)
check("get_or_default records new entry with metadata", result == "tafel")
m3 = mem2.get_meta("Tafel")
check("get_or_default metadata stored", m3 is not None and m3["origin"] == "glossary")

# clear resets both memory and meta
mem2.clear()
check("clear() empties memory", len(mem2) == 0)
check("clear() empties meta", mem2.get_meta("Sofa") is None)

# get_meta returns None for unknown key
check("get_meta None for unknown", mem.get_meta("NotInMemory") is None)


# ===========================================================================
# 7. Hybrid language detector
# ===========================================================================
print("\n=== 7. detect_hybrid_language_words ===\n")

found = detect_hybrid_language_words("Keukeninsel groot")
check("Keukeninsel detected as hybrid", any(w == "Keukeninsel" for w, _ in found))

found = detect_hybrid_language_words("Kookfeld 60 cm")
check("Kookfeld detected as hybrid", any(w == "Kookfeld" for w, _ in found))

found = detect_hybrid_language_words("kookeiland van 120 cm")
check("Clean NL: no hybrids detected", len(found) == 0)

found = detect_hybrid_language_words("Keukenleerblok wit")
check("Keukenleerblok detected as hybrid", any(w == "Keukenleerblok" for w, _ in found))

# correct form from each detected hybrid
found = detect_hybrid_language_words("Keukeninsel groot")
check("Keukeninsel correction is kookeiland", found[0][1] == "kookeiland")


# ===========================================================================
# 8. Dutch naturalness rewriter
# ===========================================================================
print("\n=== 8. nl_naturalness_rewrite ===\n")

result = nl_naturalness_rewrite("Tafel is gemaakt van massief eiken")
check("'is gemaakt van' → 'van'", "is gemaakt van" not in result and "van" in result)

result = nl_naturalness_rewrite("Set die bestaat uit 4 stoelen")
check("'die bestaat uit' → 'bestaande uit'", "die bestaat uit" not in result and "bestaande uit" in result)

result = nl_naturalness_rewrite("wordt geleverd met accessoires")
check("'wordt geleverd met' → 'inclusief'", "wordt geleverd met" not in result and "inclusief" in result)

# Clean Dutch not mutated
result = nl_naturalness_rewrite("Massief eiken tafel met laden")
check("Clean Dutch not mutated by rewriter", result == "Massief eiken tafel met laden")

# Integration: rewriter runs inside nl_post_process
result = nl_post_process("stoel is gemaakt van eiken")
check("nl_post_process applies naturalness rewrite", "is gemaakt van" not in result)


# ===========================================================================
# 9. QA critical forbidden — Round 3 additions
# ===========================================================================
print("\n=== 9. QA critical forbidden (Round 3 additions) ===\n")

# Ijzer (wrong IJ casing)
issues = nl_qa_check("Frame van Ijzer")
check("QA flags 'Ijzer' as Critical", any(i["severity"] == "Critical" and "Ijzer" in i["message"] for i in issues))

# IJs (semantic error: wrong translation of Eisen)
issues = nl_qa_check("Frame van IJs materiaal")
check("QA flags 'IJs' as Critical", any(i["severity"] == "Critical" and "IJs" in i["message"] for i in issues))

# Wielen (wrong for furniture castors)
issues = nl_qa_check("Stoel met Wielen")
check("QA flags 'Wielen' as Critical", any(i["severity"] == "Critical" and "Wielen" in i["message"] for i in issues))

# Correct forms should produce no critical issues on these topics
issues = nl_qa_check("Frame van IJzer")
crit_ij = any("Ijzer" in i["message"] or "IJs" in i["message"] for i in issues)
check("QA clean for correct 'IJzer'", not crit_ij)

issues = nl_qa_check("Stoel met rollen")
crit_rollen = any("Wielen" in i["message"] for i in issues)
check("QA clean for correct 'rollen'", not crit_rollen)


# ===========================================================================
# 10. Data structure integrity checks
# ===========================================================================
print("\n=== 10. Data structure integrity ===\n")

canon_keys = [k.lower() for k, _ in NL_FURNITURE_CANONICAL]
check("'rollen' in canonical", "rollen" in canon_keys)
check("'eisen' in canonical", "eisen" in canon_keys)

forb_keys = [k.lower() for k, _ in NL_FORBIDDEN_REPLACEMENTS]
# "Ijzer" is NOT in forbidden (handled by normalize_ij_capitalization to avoid
# case-insensitive false match against the correct "IJzer" form).
check("'wielen' in forbidden", "wielen" in forb_keys)
check("'ijs' in forbidden", "ijs" in forb_keys)
check("'ijzer' NOT in forbidden (handled by IJ normalizer)", "ijzer" not in forb_keys)

qa_crit_keys = [entry[0].lower() for entry in _NL_QA_CRITICAL_FORBIDDEN]
check("'ijzer' in QA critical", "ijzer" in qa_crit_keys)
check("'ijs' in QA critical", "ijs" in qa_crit_keys)
check("'wielen' in QA critical", "wielen" in qa_crit_keys)

# No overlap between NL canonical Dutch values and purely-German words.
# "rollen" is excluded: it is valid Dutch (castors) as well as German.
de_only_words = {"tablett", "tellerstand", "kaminset", "herrendiener", "eisen"}
canon_values = {v.lower() for _, v in NL_FURNITURE_CANONICAL}
overlap = de_only_words & canon_values
check("No purely-German words in canonical NL values", len(overlap) == 0)


# ===========================================================================
# 11. Regression: Round 2 features still working after Round 3 changes
# ===========================================================================
print("\n=== 11. Round 2 regression ===\n")

check("Mehrfarbig → meerdere kleuren", "meerdere kleuren" in nl_post_process("Mehrfarbig"))
check("Kaminset → haardset", "haardset" in nl_post_process("Kaminset Binte"))
check("Herrendiener → herenknecht", "herenknecht" in nl_post_process("Herrendiener"))
check("Tablett → dienblad", "dienblad" in nl_post_process("Tablett Wirik"))
check("Tellerstand → bordenstandaard", "bordenstandaard" in nl_post_process("Tellerstand Karou"))
check("Bügelbrettbezug → strijkplankhoes", "strijkplankhoes" in nl_post_process("Bügelbrettbezug Hexagon"))
check("Duschmatte → douchemat", "douchemat" in nl_post_process("Duschmatte Japan"))
check("Eiche Sägerau Dekor preserved", "grof gezaagde eikenlook" in nl_post_process("Eiche Sägerau Dekor"))
check("3-Sitzer Sofa → 3-zitsbank", "3-zitsbank" in nl_post_process("3-Sitzer Sofa Hayman"))
check("Kücheninsel → kookeiland", "kookeiland" in nl_post_process("Kücheninsel"))
check("Kochfeldunterkast → kookplaatonderkast", "kookplaatonderkast" in nl_post_process("Kochfeldunterkast"))
check("Korpus & Arbeitsplatte → Body & werkblad", nl_post_process("Korpus & Arbeitsplatte") == "Body & werkblad")


# ===========================================================================
# SUMMARY
# ===========================================================================
total = 72  # this suite only; add up labels above
# count total checks by failures vs passed
import traceback
total_checks = 0
for line in open(__file__).readlines():
    if line.strip().startswith("check("):
        total_checks += 1

print(f"\n{'='*60}")
print(f"Results: {total_checks - failures}/{total_checks} passed" +
      ("" if failures == 0 else f", {failures} FAILED"))
print()

sys.exit(1 if failures else 0)
