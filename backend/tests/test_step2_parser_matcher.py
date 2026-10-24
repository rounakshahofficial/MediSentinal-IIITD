"""Step 2 tests: 16 pytest cases for parser.py & matcher.py covering tricky edge cases."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from app.config import BACKEND_DIR
from app.db import Base, build_engine
from app.matcher import evaluate_listing_match, match_and_save_listing
from app.models import Listing, MatchStatus, ReferencePrice
from app.parser import parse_listing_fields, parse_pack_size
from scripts.seed_references import seed_reference_prices


def _ref(
    ref_id: int,
    ingredient: str,
    strength: str,
    dosage_form: str,
    unit: str = "1 tablet",
    ceiling: str = "2.0000",
) -> ReferencePrice:
    return ReferencePrice(
        id=ref_id,
        ingredient=ingredient,
        strength=strength,
        dosage_form=dosage_form,
        unit=unit,
        ceiling_price_per_unit=Decimal(ceiling),
        gst_percent=Decimal("12.00"),
        source_order="SAMPLE-SO-TEST",
        effective_from=date(2025, 4, 1),
        version="SAMPLE-v1",
    )


@pytest.fixture()
def reference_catalog() -> list[ReferencePrice]:
    """ Combined reference catalog for unit-testing single-family & tricky cross-form/unit cases."""
    return [
        _ref(1, "Paracetamol", "650 mg", "tablet", "1 tablet", "2.0400"),
        _ref(2, "Paracetamol", "500 mg", "tablet", "1 tablet", "1.0100"),
        _ref(3, "Paracetamol", "125 mg/5 ml", "syrup", "1 ml", "0.6200"),
        _ref(4, "Atorvastatin", "10 mg", "tablet", "1 tablet", "5.7100"),
        _ref(5, "Atorvastatin", "20 mg", "tablet", "1 tablet", "13.8600"),
        _ref(6, "Levothyroxine", "50 mcg", "tablet", "1 tablet", "1.3500"),
    ]


def test_01_single_line_paracetamol_650mg_strip_of_15(
    reference_catalog: list[ReferencePrice],
) -> None:
    res = evaluate_listing_match(
        product_name="Paracetamol 650mg Tablet, strip of 15",
        references=reference_catalog,
    )
    assert res.status == MatchStatus.MATCHED
    assert res.reference_id == 1
    assert res.parsed_ingredient == "Paracetamol"
    assert res.parsed_strength == "650 mg"
    assert res.parsed_form == "tablet"
    assert res.units_in_pack == 15
    assert res.confidence >= 0.89
    assert res.can_calculate_discrepancy is True
    assert any("Exact deterministic agreement" in r for r in res.reasons)


def test_02_strip_of_10_tablets_standard_listing(
    reference_catalog: list[ReferencePrice],
) -> None:
    units, audit, _ = parse_pack_size("Strip of 10 tablets", dosage_form="tablet")
    assert units == 10
    assert audit.raw_text == "Strip of 10 tablets"

    res = evaluate_listing_match(
        product_name="Atorva 10 Tablet",
        composition_raw="Atorvastatin (10mg)",
        pack_size_raw="Strip of 10 tablets",
        references=reference_catalog,
    )
    assert res.status == MatchStatus.MATCHED
    assert res.reference_id == 4
    assert res.units_in_pack == 10
    assert res.confidence >= 0.95
    assert res.can_calculate_discrepancy is True


def test_03_different_pack_sizes_15_and_30_match_per_unit_reference(
    reference_catalog: list[ReferencePrice],
) -> None:
    res_15 = evaluate_listing_match(
        product_name="Calpol 650 Tablet",
        composition_raw="Paracetamol (650mg)",
        pack_size_raw="Strip of 15 tablets",
        references=reference_catalog,
    )
    res_30 = evaluate_listing_match(
        product_name="Calpol 650 Economy Bottle",
        composition_raw="Paracetamol (650mg)",
        pack_size_raw="Bottle of 30 tablets",
        references=reference_catalog,
    )
    assert res_15.status == MatchStatus.MATCHED and res_15.units_in_pack == 15
    assert res_30.status == MatchStatus.MATCHED and res_30.units_in_pack == 30


def test_04_multipack_2_strips_of_10_and_3x10s(
    reference_catalog: list[ReferencePrice],
) -> None:
    combo_pack = evaluate_listing_match(
        product_name="Atorva 10 Value Pack Tablet",
        composition_raw="Atorvastatin 10 mg",
        pack_size_raw="2 strips of 10 tablets",
        references=reference_catalog,
    )
    nxm_pack = evaluate_listing_match(
        product_name="Atorva 10 Institutional Pack Tablet",
        composition_raw="Atorvastatin 10 mg",
        pack_size_raw="3 x 10's",
        references=reference_catalog,
    )
    assert combo_pack.status == MatchStatus.MATCHED and combo_pack.units_in_pack == 20
    assert nxm_pack.status == MatchStatus.MATCHED and nxm_pack.units_in_pack == 30


def test_05_unclear_pack_size_1_strip_and_pack_of_2_stops_uncertain(
    reference_catalog: list[ReferencePrice],
) -> None:
    for unclear_pack in ("1 strip", "Pack of 2", ""):
        res = evaluate_listing_match(
            product_name="Atorva 10 Tablet",
            composition_raw="Atorvastatin (10mg)",
            pack_size_raw=unclear_pack,
            references=reference_catalog,
        )
        assert res.status == MatchStatus.UNCERTAIN
        assert res.units_in_pack is None
        assert res.can_calculate_discrepancy is False
        assert any("uncertain" in r.lower() for r in res.reasons)


def test_06_pack_range_10_to_15_tablets_stops_uncertain(
    reference_catalog: list[ReferencePrice],
) -> None:
    res = evaluate_listing_match(
        product_name="Paracetamol 500mg Tablet",
        composition_raw="Paracetamol 500 mg",
        pack_size_raw="10 - 15 tablets",
        references=reference_catalog,
    )
    assert res.status == MatchStatus.UNCERTAIN
    assert res.units_in_pack is None
    assert res.can_calculate_discrepancy is False


def test_07_combination_drug_plus_operator_rejected(
    reference_catalog: list[ReferencePrice],
) -> None:
    res = evaluate_listing_match(
        product_name="Zerodol P Tablet",
        composition_raw="Aceclofenac (100mg) + Paracetamol (325mg)",
        pack_size_raw="Strip of 10 tablets",
        references=reference_catalog,
    )
    assert res.status == MatchStatus.NO_MATCH
    assert res.parsed_ingredient == "Aceclofenac + Paracetamol"
    assert res.confidence == 0.0
    assert res.can_calculate_discrepancy is False
    assert any("Multi-ingredient" in r for r in res.reasons)


def test_08_combination_drug_inline_ampersand_and_slash_rejected(
    reference_catalog: list[ReferencePrice],
) -> None:
    amp = evaluate_listing_match(
        product_name="Paracetamol 500mg & Caffeine 65mg Tablet, strip of 10",
        references=reference_catalog,
    )
    slash = evaluate_listing_match(
        product_name="Atorvastatin 10mg / Ezetimibe 10mg Tablet, strip of 10",
        references=reference_catalog,
    )
    assert amp.status == MatchStatus.NO_MATCH and amp.can_calculate_discrepancy is False
    assert slash.status == MatchStatus.NO_MATCH and slash.can_calculate_discrepancy is False


def test_09_mg_vs_mcg_mismatch_never_matches_mg_reference(
    reference_catalog: list[ReferencePrice],
) -> None:
    # Reference has Paracetamol 500 mg, NOT 500 mcg
    res = evaluate_listing_match(
        product_name="Paracetamol 500mcg Research Tablet, strip of 10",
        composition_raw="Paracetamol 500 mcg",
        pack_size_raw="Strip of 10 tablets",
        references=reference_catalog,
    )
    assert res.parsed_strength == "500 mcg"
    assert res.status == MatchStatus.NO_MATCH
    assert res.can_calculate_discrepancy is False
    assert any("Strength/unit mismatch" in r for r in res.reasons)


def test_10_mg_vs_mcg_conflict_between_title_and_composition_stops_uncertain(
    reference_catalog: list[ReferencePrice],
) -> None:
    # Title erroneously states 50mg while composition states 50 mcg -> conflict -> uncertain
    res = evaluate_listing_match(
        product_name="Thyronorm 50mg Tablet",
        composition_raw="Levothyroxine Sodium (50mcg)",
        pack_size_raw="Bottle of 100 tablets",
        references=reference_catalog,
    )
    assert res.status == MatchStatus.UNCERTAIN
    assert res.can_calculate_discrepancy is False
    assert any("Strength conflict" in r for r in res.reasons)


def test_11_microgram_unicode_symbol_and_ug_match_mcg_reference(
    reference_catalog: list[ReferencePrice],
) -> None:
    unicode_mu = evaluate_listing_match(
        product_name="Thyronorm 50 µg Tablet",
        composition_raw="Levothyroxine Sodium 50 µg",
        pack_size_raw="Bottle of 100 tablets",
        references=reference_catalog,
    )
    ascii_ug = evaluate_listing_match(
        product_name="Eltroxin 50ug Tablet, strip of 10",
        composition_raw="Levothyroxine 50 ug",
        references=reference_catalog,
    )
    assert unicode_mu.status == MatchStatus.MATCHED
    assert unicode_mu.parsed_strength == "50 mcg"
    assert unicode_mu.units_in_pack == 100
    assert ascii_ug.status == MatchStatus.MATCHED
    assert ascii_ug.parsed_strength == "50 mcg"


def test_12_syrup_vs_tablet_dosage_form_mismatch(
    reference_catalog: list[ReferencePrice],
) -> None:
    # Paracetamol 500 mg exists ONLY as 'tablet', not 'syrup'
    res = evaluate_listing_match(
        product_name="Paracetamol 500mg Oral Syrup, bottle of 60 ml",
        composition_raw="Paracetamol 500 mg",
        pack_size_raw="bottle of 60 ml",
        references=reference_catalog,
    )
    assert res.parsed_form == "syrup"
    assert res.status == MatchStatus.NO_MATCH
    assert res.can_calculate_discrepancy is False
    assert any("Dosage form mismatch" in r for r in res.reasons)


def test_13_syrup_concentration_strength_and_ml_pack_match(
    reference_catalog: list[ReferencePrice],
) -> None:
    res = evaluate_listing_match(
        product_name="Calpol Pediatric 125mg/5ml Syrup, bottle of 60 ml",
        composition_raw="Each 5 ml contains: Paracetamol IP 125mg/5ml",
        pack_size_raw="bottle of 60 ml",
        references=reference_catalog,
    )
    assert res.status == MatchStatus.MATCHED
    assert res.reference_id == 3
    assert res.parsed_strength == "125 mg/5 ml"
    assert res.parsed_form == "syrup"
    assert res.units_in_pack == 60
    assert res.can_calculate_discrepancy is True


def test_14_solid_tablet_with_liquid_ml_pack_or_form_conflict_stops_uncertain(
    reference_catalog: list[ReferencePrice],
) -> None:
    # Solid tablet with '100 ml bottle' pack -> unclear solid unit count -> uncertain
    res_ml_on_tab = evaluate_listing_match(
        product_name="Atorva 10 Tablet",
        composition_raw="Atorvastatin (10mg)",
        pack_size_raw="100 ml bottle",
        references=reference_catalog,
    )
    assert res_ml_on_tab.status == MatchStatus.UNCERTAIN
    assert res_ml_on_tab.units_in_pack is None
    assert res_ml_on_tab.can_calculate_discrepancy is False

    # Title says Syrup, pack_size_raw says 'strip of 10 tablets' -> form conflict -> uncertain
    res_form_conflict = evaluate_listing_match(
        product_name="Calpol 125mg/5ml Syrup",
        composition_raw="Paracetamol 125mg/5ml",
        pack_size_raw="strip of 10 tablets",
        references=reference_catalog,
    )
    assert res_form_conflict.status == MatchStatus.UNCERTAIN
    assert res_form_conflict.can_calculate_discrepancy is False


def test_15_salt_equivalence_clause_and_modified_release_sr_guard(
    reference_catalog: list[ReferencePrice],
) -> None:
    salt_eq = evaluate_listing_match(
        product_name="Lipitor 20mg Film-Coated Tablet",
        composition_raw="Each film-coated tablet contains: Atorvastatin Calcium IP eq. to Atorvastatin 20.0 mg",
        pack_size_raw="15's",
        references=reference_catalog,
    )
    assert salt_eq.status == MatchStatus.MATCHED
    assert salt_eq.parsed_ingredient == "Atorvastatin"
    assert salt_eq.parsed_strength == "20 mg"
    assert salt_eq.units_in_pack == 15

    # Sustained-release (SR) must NOT falsely match immediate-release 'tablet'
    sr_form = parse_listing_fields(
        product_name="Atorva 20 SR Tablet",
        composition_raw="Atorvastatin 20 mg Sustained Release",
        pack_size_raw="Strip of 10 tablets",
    )
    assert sr_form.parsed_form == "modified_release_tablet"
    sr_eval = evaluate_listing_match(
        product_name="Atorva 20 SR Tablet",
        composition_raw="Atorvastatin 20 mg Sustained Release",
        pack_size_raw="Strip of 10 tablets",
        references=reference_catalog,
    )
    assert sr_eval.status == MatchStatus.NO_MATCH


def test_16_rapidfuzz_typo_gate_missing_comp_brand_and_db_upsert(
    reference_catalog: list[ReferencePrice],
    tmp_path: Path,
) -> None:
    # Near-miss OCR/listing typo -> 'uncertain' (never auto-matched!)
    typo = evaluate_listing_match(
        product_name="Atorva 10 Tablet",
        composition_raw="Atorvastatn (10mg)",
        pack_size_raw="Strip of 10 tablets",
        references=reference_catalog,
    )
    assert typo.status == MatchStatus.UNCERTAIN
    assert 0.35 <= typo.confidence <= 0.55
    assert typo.can_calculate_discrepancy is False
    assert any("rapidfuzz" in r for r in typo.reasons)

    # Brand-only title without composition_raw -> 'uncertain'
    brand_no_comp = evaluate_listing_match(
        product_name="Dolo 650mg Tablet, strip of 15",
        composition_raw=None,
        references=reference_catalog,
    )
    assert brand_no_comp.status == MatchStatus.UNCERTAIN
    assert brand_no_comp.can_calculate_discrepancy is False

    # DB persistence check via match_and_save_listing
    engine = build_engine(f"sqlite:///{tmp_path / 'step2_upsert.db'}")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)
    with TestSession() as session:
        seed_reference_prices(session, csv_path=BACKEND_DIR / "data" / "reference_prices.csv")
        listing = Listing(
            site="1mg",
            url="https://www.1mg.com/drugs/atorva-10",
            product_name="Atorva 10 Tablet",
            composition_raw="Atorvastatin (10mg)",
            pack_size_raw="Strip of 10 tablets",
            mrp=Decimal("78.50"),
            selling_price=Decimal("69.00"),
            raw_json={},
        )
        session.add(listing)
        session.flush()
        match_row, eval_res = match_and_save_listing(session, listing)
        session.commit()
        assert match_row.status == "matched"
        assert match_row.units_in_pack == 10
        assert eval_res.raw_audit["pack_size_raw" if "pack_size_raw" in eval_res.raw_audit else "units_in_pack"].raw_text == "Strip of 10 tablets"
    engine.dispose()
