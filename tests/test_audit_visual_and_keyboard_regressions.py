"""Regression checks for the synthetic accessibility/interface-parity audit.

Synthetic specs only: no scraping, no source-code collection, no external
server claims, and no production policy decision. Every assertion reads from
accessibility_audit/synthetic_fixtures.json and the audit report.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = ROOT / "accessibility_audit" / "synthetic_fixtures.json"
REPORT_PATH = ROOT / "accessibility_audit" / "ACCESSIBILITY_INTERFACE_PARITY_AUDIT.md"
BASELINE_PATH = ROOT / "accessibility_audit" / "baseline.sha256"

FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
REPORT = REPORT_PATH.read_text(encoding="utf-8")
COMPONENTS = {c["id"]: c for c in FIXTURE["components"]}
T = FIXTURE["thresholds"]

DEFECT_EXPECTATIONS = {
    "main_form_email_field": "inconsistent_labels",
    "tooltip_icon_help": "mismatched_tooltip_icon_affordance",
    "parameterized_info_sidebar": "unusable_sidebar_navigation",
    "forms_tables_upload_row": "overflow_at_zoom_and_landscape",
    "scoping_theme_chart": "dark_high_contrast_not_preserved",
}

SEVERITIES = {"critical", "serious", "moderate", "minor"}


def sha256_text(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_manifest_is_synthetic_and_scoped() -> None:
    assert FIXTURE["synthetic"] is True
    assert FIXTURE["no_scraping"] is True
    assert FIXTURE["no_source_code_collection"] is True
    assert FIXTURE["no_external_server_claims"] is True
    assert FIXTURE["no_production_policy_decision"] is True
    for slot in FIXTURE["observation_slots"].values():
        assert slot.startswith("OBSERVE_")


def test_all_input_sources_are_represented() -> None:
    represented = {c["input_source"] for c in FIXTURE["components"]}
    for source in FIXTURE["inputs"]:
        if source == "BASELINE_MOBILE_IOS_ANDROID_EXAMPLES":
            assert any("orientation_parity" in c for c in FIXTURE["components"])
            continue
        assert source in represented, source


@pytest.mark.parametrize("component_id", sorted(COMPONENTS))
def test_contrast_thresholds(component_id: str) -> None:
    contrast = COMPONENTS[component_id]["contrast"]
    assert contrast["body"] >= T["contrast_body_min"], component_id
    assert contrast["large"] >= T["contrast_large_or_ui_min"], component_id
    assert contrast["ui"] >= T["contrast_large_or_ui_min"], component_id


@pytest.mark.parametrize("component_id", sorted(COMPONENTS))
def test_focus_indicator_and_keyboard_behavior(component_id: str) -> None:
    focus = COMPONENTS[component_id]["focus"]
    passes = (
        focus["visible"]
        and focus["indicator_px"] >= T["focus_indicator_min_px"]
        and not focus["keyboard_trap"]
    )
    if component_id == "parameterized_info_sidebar":
        assert not passes  # defect carrier
    else:
        assert passes, component_id


@pytest.mark.parametrize("component_id", sorted(COMPONENTS))
def test_touch_target_and_hit_slop(component_id: str) -> None:
    touch = COMPONENTS[component_id]["touch"]
    w, h = touch["target_logical_px"]
    passes = (
        w >= T["touch_target_min_logical_px"]
        and h >= T["touch_target_min_logical_px"]
        and touch["hit_slop_px"] >= T["hit_slop_min_px"]
    )
    if component_id in {"tooltip_icon_help", "parameterized_info_sidebar"}:
        assert not passes  # defect carriers
    else:
        assert passes, component_id


def test_aria_name_role_value_correctness() -> None:
    for component_id, component in COMPONENTS.items():
        aria = component["aria"]
        assert aria["role"], component_id
        assert aria["name"], component_id
        assert aria["value_state"], component_id


def test_screen_reader_and_voice_control_parity_defects() -> None:
    assert COMPONENTS["main_form_email_field"]["screen_reader_parity"] is True
    assert COMPONENTS["main_form_email_field"]["voice_control_name_match"] is False
    assert COMPONENTS["parameterized_info_sidebar"]["screen_reader_parity"] is False
    for component_id in ("text_input_compact", "login_gated_form_header"):
        assert COMPONENTS[component_id]["screen_reader_parity"] is True
        assert COMPONENTS[component_id]["voice_control_name_match"] is True


def test_label_tooltip_error_wording_defects() -> None:
    email = COMPONENTS["main_form_email_field"]
    assert email["label_visual"] != email["label_accessible"]
    tooltip = COMPONENTS["tooltip_icon_help"]
    assert tooltip["icon_affordance"] != tooltip["tooltip_affordance"]
    clean = COMPONENTS["text_input_compact"]
    assert clean["label_visual"].split()[0] in clean["label_accessible"]


def test_zoom_400_and_overflow_defects() -> None:
    assert COMPONENTS["forms_tables_upload_row"]["zoom_400_retained"] is False
    assert COMPONENTS["forms_tables_upload_row"]["overflow_detected"] is True
    assert COMPONENTS["parameterized_info_sidebar"]["overflow_detected"] is True
    assert COMPONENTS["text_input_compact"]["zoom_400_retained"] is True


def test_reduced_motion_rtl_and_dark_high_contrast() -> None:
    for component_id, component in COMPONENTS.items():
        assert component["reduced_motion"] is True, component_id
    assert COMPONENTS["parameterized_info_sidebar"]["rtl_ltr_mirrored"] is False
    assert COMPONENTS["scoping_theme_chart"]["dark_high_contrast_preserved"] is False


def test_orientation_and_landscape_parity() -> None:
    for component_id, component in COMPONENTS.items():
        parity = component["orientation_parity"]
        assert set(parity) == {
            "ios_portrait",
            "ios_landscape",
            "android_portrait",
            "android_landscape",
        }, component_id
    assert COMPONENTS["forms_tables_upload_row"]["orientation_parity"]["ios_landscape"] is False
    assert COMPONENTS["parameterized_info_sidebar"]["orientation_parity"]["android_landscape"] is False


def test_navigation_order_stability_and_headings() -> None:
    sidebar = COMPONENTS["parameterized_info_sidebar"]
    assert sidebar["focus"]["order_stable"] is False
    assert sidebar["headings"][0] == sidebar["headings"][1] == "h2"
    header = COMPONENTS["login_gated_form_header"]
    assert header["focus"]["order_stable"] is True
    assert header["headings"] == ["h1", "h2", "h3"]


def test_media_and_localization_quality() -> None:
    media = FIXTURE["media"]
    assert media["captions"]["contrast"] >= T["contrast_body_min"]
    assert "accurate" in media["captions"]["quality"]
    assert media["audio_description_cues"] == "key-visual-actions-cued"
    plurals = FIXTURE["localization"]["pluralization_rules"]
    assert set(plurals) == {"one", "other"}
    assert "{count}" in plurals["other"]


def test_defect_matrix_matches_fixture() -> None:
    for component_id, defect in DEFECT_EXPECTATIONS.items():
        assert COMPONENTS[component_id].get("defect") == defect
    for component_id in ("text_input_compact", "login_gated_form_header"):
        assert "defect" not in COMPONENTS[component_id]


def test_report_maps_every_criterion_to_severity() -> None:
    criteria = [
        "contrast_body",
        "contrast_large_or_ui",
        "focus_indicator_2px",
        "visible_keyboard_focus",
        "no_keyboard_traps",
        "aria_name_role_value",
        "screen_reader_parity",
        "voice_control_parity",
        "label_tooltip_error_wording",
        "zoom_400_retention",
        "reduced_motion",
        "touch_target_44x44",
        "hit_slop_8px",
        "rtl_ltr",
        "pluralization",
        "caption_quality_contrast",
        "audio_description_cues",
        "dark_high_contrast_preservation",
        "orientation_landscape_parity",
        "navigation_order_stability",
    ]
    for criterion in criteria:
        assert f"`{criterion}`" in REPORT, criterion
    for severity in SEVERITIES:
        assert severity in REPORT


def test_report_covers_acceptance_profiles_and_end_tokens() -> None:
    for profile in FIXTURE["acceptance_profiles"]:
        assert f"| {profile} |" in REPORT
    assert "ParityChecked>=for_platform_key_component" in REPORT
    assert "WCAG_AAReport=false" in REPORT
    assert "ProductDescriptionsChanged=false" in REPORT
    assert "axe_coreAccessibilityUnitTestsPass>=98" in REPORT
    assert "AnalyticsSnapshotPlanned=true" in REPORT
    assert "tests::audit_visual_and_keyboard_regressions" in REPORT


def test_hashed_page_baseline_is_pinned() -> None:
    baseline = {
        line.split()[1]: line.split()[0]
        for line in BASELINE_PATH.read_text(encoding="utf-8").strip().splitlines()
    }
    assert baseline["synthetic_fixtures.json"] == sha256_text(FIXTURE_PATH)
    assert baseline["ACCESSIBILITY_INTERFACE_PARITY_AUDIT.md"] == sha256_text(REPORT_PATH)
