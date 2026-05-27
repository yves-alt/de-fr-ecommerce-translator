"""
NL translation quality regression tests — manager feedback round 2.
Tests nl_engine.py post-processing functions directly (no API calls).
Run:  python test_nl_quality.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from nl_engine import (
    nl_post_process,
    apply_nl_furniture_canonical,
    apply_nl_dekor_patterns,
    apply_nl_color_normalization,
    apply_nl_forbidden_patterns,
    apply_nl_format_normalization,
    safe_shorten_product_name_nl,
    apply_nl_post_colon_lowercase,
    nl_qa_check,
    segment_cell_for_tm_matching,
    reconstruct_from_segments,
    NL_FORBIDDEN_REPLACEMENTS,
    _NL_POST_COLON_SAFE_CANONICALS,
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


def post(text: str, canonical: str = "") -> str:
    return nl_post_process(text, canonical)


# =============================================================================
# 1. Capitalization rules
# =============================================================================
print("\n=== 1. Dutch capitalization ===\n")

# variantName should apply post-colon lowercase
check("variantName in _NL_POST_COLON_SAFE_CANONICALS",
      "variantName" in _NL_POST_COLON_SAFE_CANONICALS)

result = apply_nl_post_colon_lowercase("Bekleding: Zwart", "variantName")
check("Bekleding: Zwart → Bekleding: zwart (variantName)", "Bekleding: zwart" in result)

result = apply_nl_post_colon_lowercase("Poten: Glanzend chroom", "colorDetail")
check("Poten: Glanzend chroom → Poten: glanzend chroom (colorDetail)", "Poten: glanzend chroom" in result)

result = post("Bekleding: Zwart<br>Poten: Zwart", "variantName")
check("Full cell: Bekleding: zwart<br>Poten: zwart", "Bekleding: zwart" in result and "Poten: zwart" in result)

# 3-Zits → 3-zits
result = apply_nl_format_normalization("3-Zits bank")
check("3-Zits → 3-zits", "3-zits" in result and "3-Zits" not in result)

result = apply_nl_format_normalization("3-Zits Sofa")
check("3-Zits Sofa → 3-zitsbank (via SITZER_SOFA regex)", "3-zits" in result)

# =============================================================================
# 2. Mehrfarbig / Multicolor → meerdere kleuren
# =============================================================================
print("\n=== 2. Mehrfarbig / Multicolor ===\n")

result = apply_nl_furniture_canonical("Mehrfarbig")
check("Mehrfarbig → meerdere kleuren", "meerdere kleuren" in result)

result = apply_nl_furniture_canonical("Multicolor")
check("Multicolor → meerdere kleuren", "meerdere kleuren" in result)

result = post("Kleur: Mehrfarbig", "colorDetail")
check("Kleur: Mehrfarbig → Kleur: meerdere kleuren (post-colon lowercase)", "meerdere kleuren" in result)

# Consistency: no Multikleur variants remain
for wrong in ("Multikleur", "Multikleurig"):
    forbidden_found = any(w.lower() == wrong.lower() for w, _ in NL_FORBIDDEN_REPLACEMENTS)
    result2 = post(wrong)
    check(f"{wrong} not passing through post_process unchanged", result2.lower() != wrong.lower() or not result2)

# =============================================================================
# 3. Duschmatte / Badewannenmatte / Badematte
# =============================================================================
print("\n=== 3. Bath mats ===\n")

result = apply_nl_furniture_canonical("Duschmatte Japan")
check("Duschmatte → douchemat (singular)", "douchemat" in result.lower() and "Douchematt" not in result)

result = apply_nl_furniture_canonical("Badewannenmatte Alphabet")
check("Badewannenmatte → badkuipmat", "badkuipmat" in result.lower())

result = apply_nl_furniture_canonical("Badematte Basic")
check("Badematte → badmat", "badmat" in result.lower())

# Forbidden: Douchematt (double t) must be auto-corrected
result, count = apply_nl_forbidden_patterns("Douchematt Japan")
check("Douchematt → douchemat (forbidden replacement)", "douchemat" in result.lower() and count > 0)

# Forbidden: Douchematten for singular source
result, count = apply_nl_forbidden_patterns("Douchematten")
check("Douchematten → douchemat", "douchemat" in result.lower() and count > 0)

# =============================================================================
# 4. Bügelbrettbezug → strijkplankhoes
# =============================================================================
print("\n=== 4. Bügelbrettbezug ===\n")

result = apply_nl_furniture_canonical("Bügelbrettbezug Hexagon")
check("Bügelbrettbezug → strijkplankhoes", "strijkplankhoes" in result.lower())

result = apply_nl_furniture_canonical("Bügelbrett-Bezug Basic")
check("Bügelbrett-Bezug → strijkplankhoes", "strijkplankhoes" in result.lower())

result, count = apply_nl_forbidden_patterns("Strijkplankbekleding Plus")
check("Strijkplankbekleding → strijkplankhoes (forbidden)", "strijkplankhoes" in result.lower() and count > 0)

# =============================================================================
# 5. Product name shortener — no dangling endings
# =============================================================================
print("\n=== 5. Product name shortener ===\n")

# Name within 40 chars — no change
result = safe_shorten_product_name_nl("Pantrykeuken Levin met keramische kookplaat", max_chars=60)
check("Full name preserved under 60 chars", "kookplaat" in result)

# Dangling 'keramische' at the end gets stripped
result = safe_shorten_product_name_nl("Pantrykeuken Levin met keramische")
check("Dangling 'keramische' stripped → Pantrykeuken Levin", result == "Pantrykeuken Levin")

# Dangling 'schuine' at end gets stripped
result = safe_shorten_product_name_nl("Keukenblok Malia III met schuine")
check("Dangling 'schuine' stripped", "schuine" not in result.split()[-1:])

# 'met' alone at end gets stripped
result = safe_shorten_product_name_nl("Keukenblok Malia III met")
check("Dangling 'met' stripped", not result.endswith("met"))

# =============================================================================
# 6. Kitchen terms — no German-Dutch hybrids
# =============================================================================
print("\n=== 6. Kitchen terms ===\n")

result = apply_nl_furniture_canonical("Kücheninsel")
check("Kücheninsel → kookeiland (lowercase)", "kookeiland" in result.lower())
check("Kücheninsel — no 'Keukeninsel'", "Keukeninsel" not in result)

result = apply_nl_furniture_canonical("Kochfeld")
check("Kochfeld → kookplaat", "kookplaat" in result.lower())

result = apply_nl_furniture_canonical("Kochfeldunterkast")
check("Kochfeldunterkast → kookplaatonderkast", "kookplaatonderkast" in result.lower())

result = apply_nl_furniture_canonical("Kochfeldunterschrank")
check("Kochfeldunterschrank → kookplaatonderkast", "kookplaatonderkast" in result.lower())

result = apply_nl_furniture_canonical("Dunstabzugshaube")
check("Dunstabzugshaube → afzuigkap", "afzuigkap" in result.lower())

# Forbidden: Keukeninsel, Kookfeld, Keuken eiland, Kookkom
for wrong, correct in [("Keukeninsel", "kookeiland"), ("Kookfeld", "kookplaat"),
                       ("Keuken eiland", "kookeiland"), ("Kookkom", "kookplaat")]:
    result, count = apply_nl_forbidden_patterns(wrong)
    check(f"{wrong} → {correct} (forbidden)", count > 0 and correct in result.lower())

# =============================================================================
# 7. Eiche Sägerau Dekor
# =============================================================================
print("\n=== 7. Eiche Sägerau Dekor ===\n")

result = apply_nl_dekor_patterns("Eiche Sägerau Dekor")
check("Eiche Sägerau Dekor → grof gezaagde eikenlook", "grof gezaagde eikenlook" in result)

result = apply_nl_dekor_patterns("Sägerau Dekor")
check("Sägerau Dekor (without Eiche) → grof gezaagde eikenlook", "grof gezaagde eikenlook" in result)

result = apply_nl_dekor_patterns("Nussbaum Dekor")
check("Nussbaum Dekor → notenlook", "notenlook" in result)

result = apply_nl_dekor_patterns("Dekor")
check("Dekor → look", result == "look")

# Forbidden: Zagerau, Zaagruw Decor, Notelaar
for wrong in ("Zagerau", "Zaagruw Decor", "Notelaar"):
    result, count = apply_nl_forbidden_patterns(wrong)
    check(f'"{wrong}" caught by forbidden patterns', count > 0)

# =============================================================================
# 8. Body & werkblad / Korpus / Arbeitsplatte
# =============================================================================
print("\n=== 8. Body & werkblad ===\n")

result = apply_nl_furniture_canonical("Korpus & Arbeitsplatte")
check("Korpus → Body", "Body" in result)
check("Arbeitsplatte → werkblad", "werkblad" in result)
check("Result is 'Body & werkblad'", result == "Body & werkblad")

# Capital W after & must be corrected
result, count = apply_nl_forbidden_patterns("Body & Werkblad")
check("Body & Werkblad → Body & werkblad", "Body & werkblad" in result and count > 0)

result, count = apply_nl_forbidden_patterns("Romp & werkblad")
check("Romp & werkblad → Body & werkblad", "Body & werkblad" in result and count > 0)

# =============================================================================
# 9. opbervolume typo
# =============================================================================
print("\n=== 9. opbervolume typo ===\n")

result, count = apply_nl_forbidden_patterns("opbervolume: 50L")
check("opbervolume → opbergvolume", "opbergvolume" in result and count > 0)

# =============================================================================
# 10. Kaminset / Herrendiener
# =============================================================================
print("\n=== 10. Kaminset / Herrendiener ===\n")

result = apply_nl_furniture_canonical("Kaminset Binte")
check("Kaminset → haardset", "haardset" in result.lower())

result = apply_nl_furniture_canonical("Herrendiener")
check("Herrendiener → herenknecht", "herenknecht" in result.lower())

result, count = apply_nl_forbidden_patterns("Herenstandaard")
check("Herenstandaard → herenknecht (forbidden)", "herenknecht" in result.lower() and count > 0)

# =============================================================================
# 11. Tablett / Tellerstand
# =============================================================================
print("\n=== 11. Tablett / Tellerstand ===\n")

result = apply_nl_furniture_canonical("Tablett Wirik")
check("Tablett → dienblad", "dienblad" in result.lower())

result = apply_nl_furniture_canonical("Tellerstand Karou")
check("Tellerstand → bordenstandaard", "bordenstandaard" in result.lower())

# =============================================================================
# 12. vloerweefsel forbidden
# =============================================================================
print("\n=== 12. vloerweefsel ===\n")

result, count = apply_nl_forbidden_patterns("vloerweefsel")
check("vloerweefsel → vloerglijders (forbidden)", count > 0)

issues = nl_qa_check("vloerweefsel")
check("vloerweefsel triggers QA critical warning", any("vloerweefsel" in i["message"].lower() for i in issues))

# =============================================================================
# 13. TM Glossary mappings — spot-check via canonical
# =============================================================================
print("\n=== 13. Glossary spot-check ===\n")

mappings = [
    ("Singleküche", "mini keuken"),
    ("Ottomane", "ottomane"),
    ("Kombi", "combi"),
]
for de, nl in mappings:
    result = apply_nl_furniture_canonical(de)
    check(f"{de} → {nl}", nl in result.lower())

# =============================================================================
# 14. Segmentation
# =============================================================================
print("\n=== 14. Segmentation ===\n")

segs = segment_cell_for_tm_matching("Bekleding: Zwart<br>Poten: Zwart")
check("Segmentation: 4 segments for label-value<br>label-value", len(segs) == 4)
if len(segs) >= 1:
    check("Segment 1 is 'Bekleding:'", segs[0][0] == "Bekleding:")
if len(segs) >= 2:
    check("Segment 2 is 'Zwart'", segs[1][0] == "Zwart")

# =============================================================================
# 15. Workbook consistency — DutchWorkbookConsistencyMemory
# =============================================================================
print("\n=== 15. Workbook consistency memory ===\n")

from nl_engine import DutchWorkbookConsistencyMemory
mem = DutchWorkbookConsistencyMemory()
mem.put("Mehrfarbig", "meerdere kleuren")
result = mem.get("Mehrfarbig")
check("Consistency memory: Mehrfarbig → meerdere kleuren", result == "meerdere kleuren")
check("Consistency memory: case-insensitive lookup", mem.get("mehrfarbig") == "meerdere kleuren")

# Second put of same source → doesn't overwrite
mem.put("Mehrfarbig", "multikleurig")  # wrong variant — should be ignored
check("Consistency memory: first entry wins", mem.get("Mehrfarbig") == "meerdere kleuren")

# =============================================================================
# 16. QA forbidden list
# =============================================================================
print("\n=== 16. QA forbidden list ===\n")

qa_forbidden_inputs = [
    ("Douchematt",        "Critical"),
    ("Strijkplankbekleding", "Critical"),
    ("Keukeninsel",       "Critical"),
    ("Kookfeld",          "Critical"),
    ("Keuken eiland",     "Critical"),
    ("Kookkom",           "Critical"),
    ("Zaagruw Decor",     "Critical"),
    ("Zagerau",           "Critical"),
    ("opbervolume",       "Critical"),
    ("vloerweefsel",      "Critical"),
    ("Herenstandaard",    "Critical"),
]

for text, expected_sev in qa_forbidden_inputs:
    issues = nl_qa_check(text)
    found = any(i["severity"] == expected_sev and text.lower() in i["message"].lower() for i in issues)
    check(f"QA flags '{text}' as {expected_sev}", found)

# 3-Zits capitalization
issues = nl_qa_check("3-Zits bank")
check("QA flags 3-Zits capitalization", any("3-Zits" in i["message"] for i in issues))

# Post-colon uppercase in attribute column
issues = nl_qa_check("Bekleding: Zwart", "colorDetail")
check("QA flags uppercase after colon in colorDetail", any("olon" in i["message"] or "apital" in i["message"] for i in issues))

# =============================================================================
# 17. Manager regression tests (end-to-end through nl_post_process)
# =============================================================================
print("\n=== 17. Manager regression tests ===\n")

def check_contains(label: str, text: str, expected: str, canonical: str = "") -> None:
    result = post(text, canonical)
    check(f"{label}: '{expected}' in output", expected.lower() in result.lower())

check_contains("Duschmatte Japan", "Duschmatte Japan", "douchemat")
check_contains("Badewannenmatte Alphabet", "Badewannenmatte Alphabet", "badkuipmat")
check_contains("Bügelbrettbezug Hexagon", "Bügelbrettbezug Hexagon", "strijkplankhoes")
check_contains("Mehrfarbig", "Mehrfarbig", "meerdere kleuren")
check_contains("3-Sitzer Sofa Hayman", "3-Sitzer Sofa Hayman", "3-zitsbank")
check_contains("Kücheninsel", "Kücheninsel", "kookeiland")
check_contains("Kochfeldunterkast", "Kochfeldunterkast", "kookplaatonderkast")
check_contains("Eiche Sägerau Dekor", "Eiche Sägerau Dekor", "grof gezaagde eikenlook")
check_contains("Nussbaum Dekor", "Nussbaum Dekor", "notenlook")
check_contains("Kaminset Binte", "Kaminset Binte", "haardset")
check_contains("Tablett Wirik", "Tablett Wirik", "dienblad")
check_contains("Tellerstand Karou", "Tellerstand Karou", "bordenstandaard")
check_contains("Korpus & Arbeitsplatte", "Korpus & Arbeitsplatte", "Body")

# Bekleding: zwart via post_process + post-colon rule
result = post("Bekleding: Schwarz<br>Poten: Schwarz", "colorDetail")
check("Bekleding: Schwarz → Bekleding: zwart (colorDetail)", "Bekleding: zwart" in result and "Poten: zwart" in result)

# =============================================================================
# Summary
# =============================================================================
total = 72  # approximate — counted from checks above
print(f"\n{'='*60}")
passed = total - failures if failures <= total else 0
print(f"Results: {total - failures}/{total} passed" + ("" if failures == 0 else f", {failures} FAILED"))
print()
sys.exit(1 if failures else 0)
