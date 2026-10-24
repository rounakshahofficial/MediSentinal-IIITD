"""Deterministic regex/rule-based parser for online pharmacy listings (Rules 1 & 8)."""

from __future__ import annotations

import re
from decimal import Decimal

from app.schemas import ParsedListingFields, RawFieldAudit

_BOILERPLATE_PREFIX_RE = re.compile(
    r"^(?:composition\s*:\s*|each\s+[a-z0-9\s\-]+?(?:tablet|capsule|ml|teaspoonful)\s+contains\s*:\s*)",
    re.IGNORECASE,
)
_EQUIVALENT_TO_RE = re.compile(
    r"\b(?:equivalent|eq\.?)\s+to\s+([a-zA-Z][a-zA-Z\s\-]+?)(?=\s*\(|\s+\d|\s*$)",
    re.IGNORECASE,
)
_INGREDIENT_BEFORE_STRENGTH_RE = re.compile(
    r"^([a-zA-Z][a-zA-Z\s\-]*?)(?=\s*\(|\s+\d|\s*$)"
)
_SALT_AND_PHARMACOPOEIA_SUFFIXES = {
    "ip",
    "bp",
    "usp",
    "ep",
    "calcium",
    "sodium",
    "potassium",
    "magnesium",
    "hydrochloride",
    "hcl",
    "besylate",
    "maleate",
    "tartrate",
    "succinate",
    "phosphate",
    "sulfate",
    "sulphate",
    "trihydrate",
    "monohydrate",
    "dihydrate",
    "anhydrous",
    "oral",
    "pediatric",
    "paediatric",
}

# Concentration strength first (e.g. "125mg/5ml", "100 mg / ml"), then scalar mass/IU strength
_CONCENTRATION_STRENGTH_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(mg|mcg|µg|μg|ug|micrograms?|milligrams?|gm?|iu)\s*/\s*(\d+(?:\.\d+)?)?\s*(ml)\b",
    re.IGNORECASE,
)
_SCALAR_STRENGTH_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(mg|mcg|µg|μg|ug|micrograms?|milligrams?|gm|g|iu)\b",
    re.IGNORECASE,
)
_TITLE_IMPLICIT_STRENGTH_RE = re.compile(
    r"^[a-zA-Z][a-zA-Z0-9\-]*\s+(\d+(?:\.\d+)?)\s+(?:tablet|tab|capsule|cap)\b",
    re.IGNORECASE,
)

_COMBINATION_SPLIT_RE = re.compile(r"\s*(?:\+|&|\bwith\b)\s*", re.IGNORECASE)
_SLASH_COMBO_RE = re.compile(r"\b([a-zA-Z]{4,})\s*/\s*([a-zA-Z]{4,})\b")
_UNIT_WORDS = {
    "mg",
    "mcg",
    "ug",
    "g",
    "gm",
    "ml",
    "iu",
    "tablet",
    "tablets",
    "capsule",
    "capsules",
    "syrup",
    "suspension",
}

_MODIFIED_RELEASE_RE = re.compile(
    r"\b(?:sr|er|xr|cr|pr|mr|sustained[\s\-]release|extended[\s\-]release|"
    r"prolonged[\s\-]release|modified[\s\-]release|controlled[\s\-]release)\b",
    re.IGNORECASE,
)
_FORM_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("tablet", re.compile(r"\b(?:tablets?|tabs?)\b", re.IGNORECASE)),
    ("capsule", re.compile(r"\b(?:capsules?|caps?)\b", re.IGNORECASE)),
    ("syrup", re.compile(r"\bsyrups?\b", re.IGNORECASE)),
    ("suspension", re.compile(r"\bsuspensions?\b", re.IGNORECASE)),
    ("injection", re.compile(r"\binjections?\b", re.IGNORECASE)),
    ("drops", re.compile(r"\bdrops\b", re.IGNORECASE)),
]
_SOLID_FORMS = {"tablet", "capsule", "modified_release_tablet", "modified_release_capsule"}
_LIQUID_FORMS = {"syrup", "suspension", "drops"}

_PACK_RANGE_RE = re.compile(r"\b\d+\s*(?:\-|to)\s*\d+\b", re.IGNORECASE)
_MULTI_CONTAINER_PACK_RE = re.compile(
    r"\b(\d+)\s*(?:strips?|packs?|boxes?)\s*(?:of|x|\*)\s*(\d+)\s*"
    r"(?:[a-z\-]+\s+)*(?:tablets?|tabs?|capsules?|caps?|units?|pills?|'s)?\b",
    re.IGNORECASE,
)
_NXM_PACK_RE = re.compile(
    r"\b(\d+)\s*[xX\*]\s*(\d+)\s*(?:tablets?|tabs?|capsules?|caps?|'s|s)\b",
    re.IGNORECASE,
)
_CONTAINER_OF_UNITS_RE = re.compile(
    r"\b(?:strip|pack|box|bottle)s?\s+of\s+(\d+)\s*"
    r"(?:[a-z\-]+\s+)*(?:tablets?|tabs?|capsules?|caps?|units?|pills?)\b",
    re.IGNORECASE,
)
# Handles e.g. "Paracetamol 650mg Tablet, strip of 15" where 'strip of N' omits trailing 'tablets'
_BLISTER_STRIP_SHORTHAND_RE = re.compile(
    r"\bstrip\s+of\s+(\d+)\b(?!\s*(?:strips?|packs?|boxes?|bottles?|ml|mg|mcg|g)\b)",
    re.IGNORECASE,
)
_PLAIN_SOLID_UNITS_RE = re.compile(
    r"\b(\d+)\s*(?:film[\s\-]coated\s+|uncoated\s+|dispersible\s+|hard\s+gelatin\s+)?"
    r"(?:tablets?|tabs?|capsules?|caps?|units?|pills?)\b",
    re.IGNORECASE,
)
_APOSTROPHE_UNITS_RE = re.compile(
    r"(?:^\s*(\d+)\s*(?:'s|s)\s*$|\b(\d+)\s*'s\b)", re.IGNORECASE
)
_LIQUID_ML_PACK_RE = re.compile(
    r"(?:\b(?:bottle|pack|vial)\s+of\s+(\d+)\s*ml\b|\b(\d+)\s*ml\s*(?:bottle|syrup|suspension|drops|pack)?\b)",
    re.IGNORECASE,
)


def _normalize_number_str(raw_number: str) -> str:
    """Format '10.0' -> '10' and '2.50' -> '2.5' deterministically."""
    dec = Decimal(raw_number).normalize()
    text = format(dec, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _canonical_mass_unit(raw_unit: str) -> str:
    """Normalize mass/potency units carefully preserving mg vs mcg distinction."""
    lowered = raw_unit.strip().lower()
    if lowered in {"mcg", "ug", "µg", "μg", "microgram", "micrograms"}:
        return "mcg"
    if lowered in {"mg", "milligram", "milligrams"}:
        return "mg"
    if lowered in {"g", "gm", "gram", "grams"}:
        return "g"
    return lowered


def _extract_normalized_strength(text: str) -> tuple[str | None, str]:
    """Extract normalized strength (concentration or scalar) and rule name."""
    conc = _CONCENTRATION_STRENGTH_RE.search(text)
    if conc:
        num = _normalize_number_str(conc.group(1))
        unit = _canonical_mass_unit(conc.group(2))
        denom = _normalize_number_str(conc.group(3)) if conc.group(3) else "1"
        vol_unit = conc.group(4).lower()
        if denom == "1":
            return f"{num} {unit}/{vol_unit}", "concentration_unit_regex"
        return f"{num} {unit}/{denom} {vol_unit}", "concentration_unit_regex"

    scal = _SCALAR_STRENGTH_RE.search(text)
    if scal:
        num = _normalize_number_str(scal.group(1))
        unit = _canonical_mass_unit(scal.group(2))
        return f"{num} {unit}", "explicit_unit_regex"

    return None, "unmatched"


def _clean_ingredient_tokens(raw_name: str) -> tuple[str | None, bool]:
    """Strip pharmacopoeial/salt suffixes and return (TitleCaseIngredient, salt_stripped)."""
    tokens = [tok for tok in re.split(r"[\s\-]+", raw_name.strip(" ,;:-")) if tok]
    salt_stripped = False
    while len(tokens) > 1 and tokens[-1].lower() in _SALT_AND_PHARMACOPOEIA_SUFFIXES:
        tokens.pop()
        salt_stripped = True
    if not tokens:
        return None, salt_stripped
    return " ".join(tok.capitalize() for tok in tokens), salt_stripped


def _detect_combination(text: str) -> bool:
    """Return True if text describes a multi-ingredient combination (FDC)."""
    cleaned = _BOILERPLATE_PREFIX_RE.sub("", text.strip())
    # Ignore trailing pack clause after comma when inspecting a combined product_name
    head = cleaned.split(",", 1)[0]
    if len(_COMBINATION_SPLIT_RE.split(head)) > 1:
        return True
    for left, right in _SLASH_COMBO_RE.findall(head):
        if left.lower() not in _UNIT_WORDS and right.lower() not in _UNIT_WORDS:
            return True
    if (
        not _EQUIVALENT_TO_RE.search(head)
        and not _CONCENTRATION_STRENGTH_RE.search(head)
        and len(_SCALAR_STRENGTH_RE.findall(head)) > 1
    ):
        return True
    return False


def _parse_combination_fields(
    source_text: str,
    source_field: str,
    notes: list[str],
) -> tuple[str | None, str | None, bool, bool, RawFieldAudit, RawFieldAudit]:
    cleaned = _BOILERPLATE_PREFIX_RE.sub("", source_text.strip()).split(",", 1)[0]
    parts = _COMBINATION_SPLIT_RE.split(cleaned)
    if len(parts) == 1 and "/" in cleaned:
        parts = [p.strip() for p in cleaned.split("/")]

    combo_names: list[str] = []
    for part in parts:
        match = _INGREDIENT_BEFORE_STRENGTH_RE.search(part.strip())
        if match:
            ing, _ = _clean_ingredient_tokens(match.group(1))
            if ing:
                combo_names.append(ing)

    joined_ing = " + ".join(combo_names) if combo_names else None
    strengths = [
        f"{_normalize_number_str(num)} {_canonical_mass_unit(unit)}"
        for num, unit in _SCALAR_STRENGTH_RE.findall(cleaned)
    ]
    joined_strength = " + ".join(strengths) if strengths else None
    notes.append(f"Multi-ingredient combination (FDC) detected in {source_field}.")
    return (
        joined_ing,
        joined_strength,
        True,
        False,
        RawFieldAudit(
            raw_text=source_text,
            normalized_value=joined_ing,
            source_field=source_field,
            rule_applied="fdc_combination_split",
        ),
        RawFieldAudit(
            raw_text=source_text,
            normalized_value=joined_strength,
            source_field=source_field,
            rule_applied="fdc_strength_join",
        ),
    )


def _extract_ingredient_and_strength(
    product_name: str,
    composition_raw: str | None,
    notes: list[str],
) -> tuple[str | None, str | None, bool, bool, RawFieldAudit, RawFieldAudit]:
    """Extract normalized ingredient and strength with raw provenance & conflict checks."""
    # Fallback path when composition_raw is omitted (e.g. "Paracetamol 650mg Tablet, strip of 15")
    if not composition_raw or not composition_raw.strip():
        if _detect_combination(product_name):
            return _parse_combination_fields(product_name, "product_name", notes)

        title_head = product_name.strip().split(",", 1)[0]
        title_strength, str_rule = _extract_normalized_strength(title_head)
        if title_strength is None:
            notes.append(
                "composition_raw is missing and product_name has no explicit strength unit (mg/mcg/g)."
            )
            return (
                None,
                None,
                False,
                False,
                RawFieldAudit(raw_text=composition_raw, source_field="composition_raw", rule_applied="missing"),
                RawFieldAudit(raw_text=product_name, source_field="product_name", rule_applied="missing_explicit_unit"),
            )

        ing_match = _INGREDIENT_BEFORE_STRENGTH_RE.search(title_head)
        raw_ing = ing_match.group(1) if ing_match else ""
        parsed_ing, _ = _clean_ingredient_tokens(raw_ing)
        notes.append(
            "composition_raw was absent; extracted candidate ingredient and explicit strength from product_name."
        )
        return (
            parsed_ing,
            title_strength,
            False,
            False,
            RawFieldAudit(
                raw_text=product_name,
                normalized_value=parsed_ing,
                source_field="product_name",
                rule_applied="title_prefix_before_explicit_strength",
            ),
            RawFieldAudit(
                raw_text=product_name,
                normalized_value=title_strength,
                source_field="product_name",
                rule_applied=str_rule,
            ),
        )

    if _detect_combination(composition_raw) or _detect_combination(product_name):
        source = composition_raw if _detect_combination(composition_raw) else product_name
        field_name = "composition_raw" if source == composition_raw else "product_name"
        return _parse_combination_fields(source, field_name, notes)

    cleaned = _BOILERPLATE_PREFIX_RE.sub("", composition_raw.strip())
    eq_match = _EQUIVALENT_TO_RE.search(cleaned)
    if eq_match:
        raw_ing_segment = eq_match.group(1)
        parsed_ing, _ = _clean_ingredient_tokens(raw_ing_segment)
        ing_rule = "equivalent_to_clause"
        tail_for_strength = cleaned[eq_match.end() :]
    else:
        ing_match = _INGREDIENT_BEFORE_STRENGTH_RE.search(cleaned)
        raw_ing_segment = ing_match.group(1) if ing_match else ""
        parsed_ing, salt_stripped = _clean_ingredient_tokens(raw_ing_segment)
        ing_rule = "salt_suffix_stripped" if salt_stripped else "direct_prefix"
        if salt_stripped and parsed_ing:
            notes.append(
                f"Normalized pharmacopoeial/salt name '{raw_ing_segment.strip()}' to '{parsed_ing}'."
            )
        tail_for_strength = cleaned

    parsed_strength, strength_rule = _extract_normalized_strength(tail_for_strength)
    if parsed_strength is None:
        parsed_strength, strength_rule = _extract_normalized_strength(cleaned)
    if parsed_strength is None:
        notes.append("Could not extract explicit numeric strength from composition_raw.")

    # Cross-check product_name for conflicting strength claims (including mg vs mcg!)
    has_conflict = False
    title_head = product_name.strip().split(",", 1)[0]
    title_strength, _ = _extract_normalized_strength(title_head)
    if title_strength and parsed_strength and title_strength != parsed_strength:
        has_conflict = True
        notes.append(
            f"Strength conflict: product_name states '{title_strength}' "
            f"but composition_raw states '{parsed_strength}'."
        )
    elif parsed_strength and not title_strength:
        title_implicit = _TITLE_IMPLICIT_STRENGTH_RE.search(title_head)
        if title_implicit:
            implicit_num = _normalize_number_str(title_implicit.group(1))
            comp_num_only = parsed_strength.split()[0]
            if implicit_num != comp_num_only:
                has_conflict = True
                notes.append(
                    f"Strength conflict: product_name implies '{implicit_num}' "
                    f"but composition_raw states '{parsed_strength}'."
                )

    return (
        parsed_ing,
        parsed_strength,
        False,
        has_conflict,
        RawFieldAudit(
            raw_text=composition_raw,
            normalized_value=parsed_ing,
            source_field="composition_raw",
            rule_applied=ing_rule,
        ),
        RawFieldAudit(
            raw_text=composition_raw,
            normalized_value=parsed_strength,
            source_field="composition_raw",
            rule_applied=strength_rule,
        ),
    )


def _forms_in_text(text: str | None) -> list[str]:
    if not text:
        return []
    return [canonical for canonical, pattern in _FORM_PATTERNS if pattern.search(text)]


def _extract_dosage_form(
    product_name: str,
    composition_raw: str | None,
    pack_size_raw: str | None,
    notes: list[str],
) -> tuple[str | None, bool, RawFieldAudit]:
    """Extract canonical dosage form and check for cross-field conflicts or SR/ER modifiers."""
    title_forms = _forms_in_text(product_name)
    pack_forms = _forms_in_text(pack_size_raw)
    comp_forms = _forms_in_text(composition_raw)

    has_conflict = False
    if title_forms and pack_forms and set(title_forms) != set(pack_forms):
        has_conflict = True
        notes.append(
            f"Dosage form conflict: product_name indicates '{title_forms[0]}' "
            f"but pack_size_raw indicates '{pack_forms[0]}'."
        )

    chosen_source = "product_name"
    chosen_raw: str | None = product_name
    base_form: str | None = None
    if title_forms:
        base_form = title_forms[0]
    elif pack_forms:
        base_form = pack_forms[0]
        chosen_source = "pack_size_raw"
        chosen_raw = pack_size_raw
    elif comp_forms:
        base_form = comp_forms[0]
        chosen_source = "composition_raw"
        chosen_raw = composition_raw
    else:
        notes.append("Dosage form could not be deterministically identified.")
        return (
            None,
            has_conflict,
            RawFieldAudit(
                raw_text=f"{product_name} | {pack_size_raw or ''}",
                normalized_value=None,
                source_field="product_name/pack_size_raw",
                rule_applied="unmatched",
            ),
        )

    combined_text = f"{product_name} {composition_raw or ''}"
    rule_name = "canonical_form_regex"
    if base_form in {"tablet", "capsule"} and _MODIFIED_RELEASE_RE.search(combined_text):
        base_form = f"modified_release_{base_form}"
        rule_name = "modified_release_qualifier"
        notes.append(f"Modified-release qualifier detected; normalized form to '{base_form}'.")

    return (
        base_form,
        has_conflict,
        RawFieldAudit(
            raw_text=chosen_raw,
            normalized_value=base_form,
            source_field=chosen_source,
            rule_applied=rule_name,
        ),
    )


def parse_pack_size(
    pack_text: str | None,
    dosage_form: str | None = None,
    source_field: str = "pack_size_raw",
) -> tuple[int | None, RawFieldAudit, list[str]]:
    """Deterministically parse countable units in pack; return None when unclear."""
    local_notes: list[str] = []
    if not pack_text or not pack_text.strip():
        local_notes.append(f"{source_field} is missing; units_in_pack is unclear.")
        return (
            None,
            RawFieldAudit(
                raw_text=pack_text,
                normalized_value=None,
                source_field=source_field,
                rule_applied="missing",
            ),
            local_notes,
        )

    text = pack_text.strip()
    if _PACK_RANGE_RE.search(text):
        local_notes.append(f"Pack size '{text}' contains an ambiguous numeric range.")
        return (
            None,
            RawFieldAudit(
                raw_text=pack_text,
                normalized_value=None,
                source_field=source_field,
                rule_applied="rejected_range",
            ),
            local_notes,
        )

    # Liquid volume packs (ml) are valid ONLY for liquid dosage forms (syrup/suspension/drops)
    ml_match = _LIQUID_ML_PACK_RE.search(text)
    if ml_match and dosage_form in _LIQUID_FORMS:
        ml_val = int(ml_match.group(1) or ml_match.group(2))
        if ml_val > 0:
            return (
                ml_val,
                RawFieldAudit(
                    raw_text=pack_text,
                    normalized_value=ml_val,
                    source_field=source_field,
                    rule_applied="liquid_ml_volume",
                ),
                local_notes,
            )

    if ml_match and dosage_form in _SOLID_FORMS:
        local_notes.append(
            f"Pack size '{text}' states liquid volume (ml) for solid dosage form '{dosage_form}'."
        )
        return (
            None,
            RawFieldAudit(
                raw_text=pack_text,
                normalized_value=None,
                source_field=source_field,
                rule_applied="solid_liquid_pack_mismatch",
            ),
            local_notes,
        )

    # Solid dosage form packs: reject if dosage_form is explicitly liquid
    if dosage_form not in _LIQUID_FORMS:
        for rule_name, pattern, multiply in (
            ("multi_container_pack", _MULTI_CONTAINER_PACK_RE, True),
            ("nxm_pack", _NXM_PACK_RE, True),
            ("container_of_units", _CONTAINER_OF_UNITS_RE, False),
            ("blister_strip_shorthand", _BLISTER_STRIP_SHORTHAND_RE, False),
            ("plain_unit_count", _PLAIN_SOLID_UNITS_RE, False),
        ):
            match = pattern.search(text)
            if match:
                # Guard multi_container_pack against bare "2 packs of 1" without unit noun unless strip
                if rule_name == "multi_container_pack":
                    matched_str = match.group(0).lower()
                    if not any(
                        tok in matched_str
                        for tok in ("tablet", "tab", "capsule", "cap", "unit", "pill", "'s", "strip")
                    ):
                        continue
                units = (
                    int(match.group(1)) * int(match.group(2))
                    if multiply
                    else int(match.group(1))
                )
                if units > 0:
                    return (
                        units,
                        RawFieldAudit(
                            raw_text=pack_text,
                            normalized_value=units,
                            source_field=source_field,
                            rule_applied=rule_name,
                        ),
                        local_notes,
                    )

        apo_match = _APOSTROPHE_UNITS_RE.search(text)
        if apo_match:
            raw_num = apo_match.group(1) or apo_match.group(2)
            units = int(raw_num)
            if units > 0:
                return (
                    units,
                    RawFieldAudit(
                        raw_text=pack_text,
                        normalized_value=units,
                        source_field=source_field,
                        rule_applied="apostrophe_s_count",
                    ),
                    local_notes,
                )

    local_notes.append(f"Pack size '{text}' does not specify a clear unit count.")
    return (
        None,
        RawFieldAudit(
            raw_text=pack_text,
            normalized_value=None,
            source_field=source_field,
            rule_applied="ambiguous_pack_size",
        ),
        local_notes,
    )


def parse_listing_fields(
    product_name: str,
    composition_raw: str | None = None,
    pack_size_raw: str | None = None,
) -> ParsedListingFields:
    """Parse ingredient, strength, dosage form, and units_in_pack deterministically (Rules 1 & 8)."""
    notes: list[str] = []

    (
        ingredient,
        strength,
        is_combination,
        str_conflict,
        ing_audit,
        str_audit,
    ) = _extract_ingredient_and_strength(product_name, composition_raw, notes)

    form, form_conflict, form_audit = _extract_dosage_form(
        product_name, composition_raw, pack_size_raw, notes
    )

    if pack_size_raw and pack_size_raw.strip():
        units_in_pack, pack_audit, pack_notes = parse_pack_size(
            pack_size_raw, dosage_form=form, source_field="pack_size_raw"
        )
    else:
        # Support inline pack strings such as "Paracetamol 650mg Tablet, strip of 15"
        inline_segment = (
            product_name.split(",", 1)[1].strip() if "," in product_name else product_name
        )
        # Avoid mistaking "Paracetamol 650mg Tablet" ("1 tablet" implied? No!) for plain_unit_count
        units_in_pack, pack_audit, pack_notes = _parse_inline_pack_from_title(
            product_name, inline_segment, form
        )

    notes.extend(pack_notes)
    return ParsedListingFields(
        parsed_ingredient=ingredient,
        parsed_strength=strength,
        parsed_form=form,
        units_in_pack=units_in_pack,
        is_combination=is_combination,
        has_conflict=str_conflict or form_conflict,
        raw_audit={
            "ingredient": ing_audit,
            "strength": str_audit,
            "dosage_form": form_audit,
            "units_in_pack": pack_audit,
        },
        parse_notes=notes,
    )


def _parse_inline_pack_from_title(
    full_title: str,
    inline_segment: str,
    dosage_form: str | None,
) -> tuple[int | None, RawFieldAudit, list[str]]:
    """Extract pack count from a single-line title only when an explicit pack phrase exists."""
    # If there is a comma clause (e.g. ", strip of 15" or ", 10 tablets"), parse that clause directly
    if "," in full_title:
        return parse_pack_size(
            inline_segment,
            dosage_form=dosage_form,
            source_field="product_name",
        )

    # Without a comma, only accept explicit container/strip/x/'s pack expressions so
    # "Paracetamol 650mg Tablet" alone never mistakes "650mg Tablet" for a pack count!
    for rule_name, pattern, multiply in (
        ("multi_container_pack", _MULTI_CONTAINER_PACK_RE, True),
        ("nxm_pack", _NXM_PACK_RE, True),
        ("container_of_units", _CONTAINER_OF_UNITS_RE, False),
        ("blister_strip_shorthand", _BLISTER_STRIP_SHORTHAND_RE, False),
    ):
        match = pattern.search(full_title)
        if match:
            units = (
                int(match.group(1)) * int(match.group(2))
                if multiply
                else int(match.group(1))
            )
            return (
                units,
                RawFieldAudit(
                    raw_text=full_title,
                    normalized_value=units,
                    source_field="product_name",
                    rule_applied=rule_name,
                ),
                [],
            )

    if dosage_form in _LIQUID_FORMS:
        ml_match = _LIQUID_ML_PACK_RE.search(full_title)
        if ml_match:
            ml_val = int(ml_match.group(1) or ml_match.group(2))
            return (
                ml_val,
                RawFieldAudit(
                    raw_text=full_title,
                    normalized_value=ml_val,
                    source_field="product_name",
                    rule_applied="liquid_ml_volume",
                ),
                [],
            )

    return (
        None,
        RawFieldAudit(
            raw_text=None,
            normalized_value=None,
            source_field="pack_size_raw",
            rule_applied="missing",
        ),
        ["pack_size_raw is missing and no explicit pack clause was found in product_name."],
    )
