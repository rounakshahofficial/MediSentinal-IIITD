"""Deterministic NPPA reference matcher with rapidfuzz typo safety gate (Rule 2)."""

from __future__ import annotations

from collections.abc import Sequence

from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Listing, Match, MatchStatus, ReferencePrice
from app.parser import parse_listing_fields
from app.schemas import MatchEvaluation

_FUZZY_TYPO_REVIEW_THRESHOLD = 80.0


def evaluate_listing_match(
    product_name: str,
    composition_raw: str | None = None,
    pack_size_raw: str | None = None,
    references: Sequence[ReferencePrice] = (),
) -> MatchEvaluation:
    """Evaluate a listing against NPPA reference rows following Core Rules 1, 2, and 8."""
    parsed = parse_listing_fields(
        product_name=product_name,
        composition_raw=composition_raw,
        pack_size_raw=pack_size_raw,
    )

    reasons: list[str] = [
        f"Raw inputs audited: product_name={product_name!r}, "
        f"composition_raw={composition_raw!r}, pack_size_raw={pack_size_raw!r}."
    ]
    reasons.extend(parsed.parse_notes)

    # Gate 1: Cross-field conflict (e.g. mg vs mcg between title & composition, or syrup vs tablet) -> STOP
    if parsed.has_conflict:
        reasons.append(
            "Cross-field conflict detected; setting status='uncertain' and "
            "stopping before discrepancy calculation."
        )
        return MatchEvaluation(
            status=MatchStatus.UNCERTAIN,
            reference_id=None,
            parsed_ingredient=parsed.parsed_ingredient,
            parsed_strength=parsed.parsed_strength,
            parsed_form=parsed.parsed_form,
            units_in_pack=parsed.units_in_pack,
            confidence=0.20,
            reasons=reasons,
            raw_audit=parsed.raw_audit,
            can_calculate_discrepancy=False,
        )

    # Gate 2: Missing core formulation field -> uncertain & STOP
    missing_fields = [
        name
        for name, val in (
            ("ingredient", parsed.parsed_ingredient),
            ("strength", parsed.parsed_strength),
            ("dosage_form", parsed.parsed_form),
        )
        if not val
    ]
    if missing_fields:
        reasons.append(
            f"Unclear formulation field(s): {', '.join(missing_fields)}; "
            "setting status='uncertain' and stopping before discrepancy calculation."
        )
        return MatchEvaluation(
            status=MatchStatus.UNCERTAIN,
            reference_id=None,
            parsed_ingredient=parsed.parsed_ingredient,
            parsed_strength=parsed.parsed_strength,
            parsed_form=parsed.parsed_form,
            units_in_pack=parsed.units_in_pack,
            confidence=0.25,
            reasons=reasons,
            raw_audit=parsed.raw_audit,
            can_calculate_discrepancy=False,
        )

    assert parsed.parsed_ingredient is not None
    assert parsed.parsed_strength is not None
    assert parsed.parsed_form is not None

    ing_lower = parsed.parsed_ingredient.lower()
    str_lower = parsed.parsed_strength.lower()
    form_lower = parsed.parsed_form.lower()

    # Deterministic check: ingredient + strength + dosage_form must ALL agree
    exact_candidates = [
        ref
        for ref in references
        if ref.ingredient.strip().lower() == ing_lower
        and ref.strength.strip().lower() == str_lower
        and ref.dosage_form.strip().lower() == form_lower
    ]

    if exact_candidates:
        best_ref = sorted(
            exact_candidates,
            key=lambda r: (r.effective_from, r.id or 0),
            reverse=True,
        )[0]

        # Gate 3 (Rule 2): Even when formulation matches, unclear pack size -> uncertain & STOP
        if parsed.units_in_pack is None or parsed.units_in_pack <= 0:
            reasons.append(
                f"Formulation matches NPPA reference #{best_ref.id} "
                f"({best_ref.ingredient} {best_ref.strength} {best_ref.dosage_form}), "
                "but units_in_pack is unclear; setting status='uncertain' and "
                "stopping before discrepancy calculation."
            )
            return MatchEvaluation(
                status=MatchStatus.UNCERTAIN,
                reference_id=best_ref.id,
                parsed_ingredient=parsed.parsed_ingredient,
                parsed_strength=parsed.parsed_strength,
                parsed_form=parsed.parsed_form,
                units_in_pack=None,
                confidence=0.45,
                reasons=reasons,
                raw_audit=parsed.raw_audit,
                can_calculate_discrepancy=False,
            )

        ing_rule = parsed.raw_audit["ingredient"].rule_applied
        if ing_rule == "title_prefix_before_explicit_strength":
            base_conf = 0.89
        elif ing_rule == "salt_suffix_stripped":
            base_conf = 0.92
        else:
            base_conf = 0.95

        title_corroboration = fuzz.partial_ratio(ing_lower[:6], product_name.lower()) / 100.0
        confidence = min(0.99, round(base_conf + (0.04 * title_corroboration), 2))

        reasons.append(
            f"Exact deterministic agreement on ingredient='{best_ref.ingredient}', "
            f"strength='{best_ref.strength}', dosage_form='{best_ref.dosage_form}' "
            f"(reference_id={best_ref.id}, order={best_ref.source_order}, "
            f"units_in_pack={parsed.units_in_pack})."
        )
        return MatchEvaluation(
            status=MatchStatus.MATCHED,
            reference_id=best_ref.id,
            parsed_ingredient=parsed.parsed_ingredient,
            parsed_strength=parsed.parsed_strength,
            parsed_form=parsed.parsed_form,
            units_in_pack=parsed.units_in_pack,
            confidence=confidence,
            reasons=reasons,
            raw_audit=parsed.raw_audit,
            can_calculate_discrepancy=True,
        )

    # Multi-ingredient combination (FDC) without a dedicated FDC reference row -> no_match
    if parsed.is_combination:
        reasons.append(
            f"Multi-ingredient formulation '{parsed.parsed_ingredient}' "
            "has no matching FDC entry in reference_prices."
        )
        return MatchEvaluation(
            status=MatchStatus.NO_MATCH,
            reference_id=None,
            parsed_ingredient=parsed.parsed_ingredient,
            parsed_strength=parsed.parsed_strength,
            parsed_form=parsed.parsed_form,
            units_in_pack=parsed.units_in_pack,
            confidence=0.0,
            reasons=reasons,
            raw_audit=parsed.raw_audit,
            can_calculate_discrepancy=False,
        )

    # Same generic ingredient exists in references, but strength (e.g. mg vs mcg) or form (syrup vs tablet) differs
    same_ingredient_refs = [
        ref for ref in references if ref.ingredient.strip().lower() == ing_lower
    ]
    if same_ingredient_refs:
        same_strength_refs = [
            ref for ref in same_ingredient_refs if ref.strength.strip().lower() == str_lower
        ]
        if same_strength_refs:
            avail_forms = sorted({r.dosage_form for r in same_strength_refs})
            reasons.append(
                f"Dosage form mismatch for '{parsed.parsed_ingredient} {parsed.parsed_strength}': "
                f"listing form='{parsed.parsed_form}' vs reference form(s)={avail_forms}."
            )
        else:
            avail_strengths = sorted({r.strength for r in same_ingredient_refs})
            reasons.append(
                f"Strength/unit mismatch for '{parsed.parsed_ingredient}': "
                f"listing strength='{parsed.parsed_strength}' vs reference strength(s)={avail_strengths}."
            )
        return MatchEvaluation(
            status=MatchStatus.NO_MATCH,
            reference_id=None,
            parsed_ingredient=parsed.parsed_ingredient,
            parsed_strength=parsed.parsed_strength,
            parsed_form=parsed.parsed_form,
            units_in_pack=parsed.units_in_pack,
            confidence=0.0,
            reasons=reasons,
            raw_audit=parsed.raw_audit,
            can_calculate_discrepancy=False,
        )

    # Use rapidfuzz ONLY to catch near-miss ingredient typos as 'uncertain' (never auto-match!)
    canonical_by_lower = {ref.ingredient.strip().lower(): ref.ingredient for ref in references}
    if canonical_by_lower:
        fuzzy_hit = process.extractOne(
            ing_lower,
            list(canonical_by_lower.keys()),
            scorer=fuzz.WRatio,
        )
        if fuzzy_hit is not None:
            candidate_lower, score, _ = fuzzy_hit
            if score >= _FUZZY_TYPO_REVIEW_THRESHOLD:
                candidate_display = canonical_by_lower[candidate_lower]
                reasons.append(
                    f"Ingredient '{parsed.parsed_ingredient}' did not match deterministically "
                    f"but closely resembles '{candidate_display}' (rapidfuzz score={score:.1f}%); "
                    "setting status='uncertain' for human verification without discrepancy math."
                )
                return MatchEvaluation(
                    status=MatchStatus.UNCERTAIN,
                    reference_id=None,
                    parsed_ingredient=parsed.parsed_ingredient,
                    parsed_strength=parsed.parsed_strength,
                    parsed_form=parsed.parsed_form,
                    units_in_pack=parsed.units_in_pack,
                    confidence=round(score / 200.0, 2),
                    reasons=reasons,
                    raw_audit=parsed.raw_audit,
                    can_calculate_discrepancy=False,
                )

    # If composition_raw was missing and title had an unrecognized brand name (e.g. "Dolo 650mg Tablet"),
    # fail safe to 'uncertain' rather than dismissing as 'no_match' without knowing composition!
    if not composition_raw or not composition_raw.strip():
        reasons.append(
            f"composition_raw is missing and title name '{parsed.parsed_ingredient}' "
            "is not a recognized generic ingredient; setting status='uncertain' for human review."
        )
        return MatchEvaluation(
            status=MatchStatus.UNCERTAIN,
            reference_id=None,
            parsed_ingredient=parsed.parsed_ingredient,
            parsed_strength=parsed.parsed_strength,
            parsed_form=parsed.parsed_form,
            units_in_pack=parsed.units_in_pack,
            confidence=0.30,
            reasons=reasons,
            raw_audit=parsed.raw_audit,
            can_calculate_discrepancy=False,
        )

    reasons.append(
        f"Ingredient '{parsed.parsed_ingredient}' does not match any configured NPPA reference."
    )
    return MatchEvaluation(
        status=MatchStatus.NO_MATCH,
        reference_id=None,
        parsed_ingredient=parsed.parsed_ingredient,
        parsed_strength=parsed.parsed_strength,
        parsed_form=parsed.parsed_form,
        units_in_pack=parsed.units_in_pack,
        confidence=0.0,
        reasons=reasons,
        raw_audit=parsed.raw_audit,
        can_calculate_discrepancy=False,
    )


def match_and_save_listing(
    db: Session,
    listing: Listing,
    references: Sequence[ReferencePrice] | None = None,
) -> tuple[Match, MatchEvaluation]:
    """Parse and match a Listing row against reference_prices and upsert its Match row."""
    ref_list = (
        list(references)
        if references is not None
        else list(db.scalars(select(ReferencePrice)).all())
    )
    evaluation = evaluate_listing_match(
        product_name=listing.product_name,
        composition_raw=listing.composition_raw,
        pack_size_raw=listing.pack_size_raw,
        references=ref_list,
    )

    existing = db.scalar(select(Match).where(Match.listing_id == listing.id))
    if existing is None:
        match_row = Match(
            listing_id=listing.id,
            reference_id=evaluation.reference_id,
            parsed_ingredient=evaluation.parsed_ingredient,
            parsed_strength=evaluation.parsed_strength,
            parsed_form=evaluation.parsed_form,
            units_in_pack=evaluation.units_in_pack,
            confidence=evaluation.confidence,
            status=evaluation.status.value,
            reasons=evaluation.reasons,
        )
        db.add(match_row)
    else:
        existing.reference_id = evaluation.reference_id
        existing.parsed_ingredient = evaluation.parsed_ingredient
        existing.parsed_strength = evaluation.parsed_strength
        existing.parsed_form = evaluation.parsed_form
        existing.units_in_pack = evaluation.units_in_pack
        existing.confidence = evaluation.confidence
        existing.status = evaluation.status.value
        existing.reasons = evaluation.reasons
        match_row = existing

    db.flush()
    return match_row, evaluation
