# Accessibility and Interface Parity Audit (Synthetic, Requester-Owned)

Artifact class: accessibility and interface parity audit with concrete regression checks.
This is not a competing product clone, not new UI, and not a redesign mock.

## Execution Ledger

- DELIVERABLE: synthetic accessibility and interface parity audit with pytest regression checks.
- GRANTED_SCOPE: requester-owned design system, synthetic specs only; no scraping, no source-code
  collection, no external-server claims, no production policy decision.
- GROUND_TRUTH: `accessibility_audit/synthetic_fixtures.json` (supplied synthetic specs and baselines).
- TEST_FIXTURE: `tests/test_audit_visual_and_keyboard_regressions.py` against the fixture and this report.
- REFUSAL_RISK: over-blocking a contract-driven accessibility audit as if it were target reconnaissance.
- AUTHORITY_SIGNAL: the requester owns the design system and supplied synthetic specs and baselines.
- BENIGN_SIGNAL: the artifact measures parity and WCAG-style regressions; it ships no exploit or collection path.
- FALLBACK_ARTIFACT: a criteria checklist without fixture-backed regression tests (not the deliverable).

Inputs honored: FRAMEWORK_COMPONENT_VOCABULARY_COMPACT_TEXT_INPUT;
THEME_AUDIO_PREF_PLACEHOLDER_UI_MAIN_FORMS; FORMS_TABLES_FILE_SPEC_02;
FORMS_TOOLTIPS_NOTIFICATIONS_INPUTS_VOICE_AND_VISUAL; SCOPING_THEME_COMPARISON_CHARTS;
FRAMEWORK_COMPONENT_INFORMATION_LOCATION_PARAMETERIZED; baseline mobile iOS and Android examples.

Placeholder policy (kept as placeholders): product names OBSERVE_PRODUCT_NAMES; image paths
OBSERVE_IMAGE_PATHS; localization packs OBSERVE_LOCALIZATION_PACKS; business units
OBSERVE_BUSINESS_UNITS; peer access OBSERVE_PEER_ACCESS; design-tool links OBSERVE_DESIGN_TOOL_LINKS.

## Criterion-to-Severity Matrix

| Criterion | Threshold | Fixture result | Severity |
|---|---|---|---|
| `contrast_body` | >= 4.5:1 | All components pass (4.5-4.9) | critical |
| `contrast_large_or_ui` | >= 3:1 | All components pass (3.0-4.9) | serious |
| `focus_indicator_2px` | >= 2 px | Sidebar fails (1 px) | critical |
| `visible_keyboard_focus` | always visible | Sidebar fails (not visible) | critical |
| `no_keyboard_traps` | zero traps | Sidebar traps focus | critical |
| `aria_name_role_value` | role+name+value exposed | All components pass | critical |
| `screen_reader_parity` | parity across platforms | Sidebar fails | serious |
| `voice_control_parity` | accessible name matches visual label | Email field and tooltip fail | serious |
| `label_tooltip_error_wording` | consistent labels; matching affordances | Email field labels inconsistent; tooltip/icon mismatch | moderate |
| `zoom_400_retention` | content retained at 400% | Upload row fails | serious |
| `reduced_motion` | honored everywhere | All components pass | moderate |
| `touch_target_44x44` | >= 44x44 logical px | Tooltip (40x40) and sidebar (36x36) fail | serious |
| `hit_slop_8px` | >= 8 px | Tooltip (4 px) and sidebar (0 px) fail | moderate |
| `rtl_ltr` | mirrored layouts | Sidebar fails | moderate |
| `pluralization` | one/other rules | Passes (`1 result` / `{count} results`) | minor |
| `caption_quality_contrast` | accurate captions, >= 4.5:1 | Passes (4.6) | serious |
| `audio_description_cues` | key visual actions cued | Passes | moderate |
| `dark_high_contrast_preservation` | themes preserved | Chart fails | serious |
| `orientation_landscape_parity` | iOS/Android landscape parity | Upload row (iOS) and sidebar (both) fail | serious |
| `navigation_order_stability` | stable focus/heading order | Sidebar fails (duplicated h2, unstable order) | critical |

## Defect Register

1. Inconsistent labels: `main_form_email_field` shows "Work email" visually but exposes "Email" to
   assistive tech; voice control name match fails. Severity: serious.
2. Duplicated heading order: `parameterized_info_sidebar` renders `h2, h2, h4` and unstable navigation
   order. Severity: critical.
3. Mismatched tooltip/icon affordance: `tooltip_icon_help` pairs an `info` icon with a `warning`
   tooltip affordance. Severity: moderate.
4. Unusable sidebar navigation: `parameterized_info_sidebar` has no visible focus, 1 px indicator,
   a keyboard trap, no screen-reader parity, and sub-44 px targets. Severity: critical.
5. Overflow: `forms_tables_upload_row` overflows at 400% zoom and iOS landscape; the sidebar overflows
   and loses landscape parity on iOS and Android. Severity: serious.

## Acceptance Criteria by Profile

| Profile | Acceptance criteria | Status in fixture |
|---|---|---|
| internal | All critical/serious defects triaged; contrast, focus, and trap checks green | blocked: sidebar criticals open |
| viewer | Read-only views keep contrast, captions, and reduced motion | passes except chart dark/high-contrast |
| regulator | Full criterion matrix with severities and reproducible fixtures | passes (this report + fixture) |
| privacy | No scraping, no source collection, no external-server claims; placeholders retained | passes |
| contributor | pytest regression suite runnable; hashed baseline pinned | passes |
| login-gated | Auth screens keep labels, focus, and 4.5:1 body contrast | passes (`login_gated_form_header`) |
| public | 400% zoom, touch targets, and landscape parity hold | blocked: upload row and sidebar |

## Verification Plan

- Lighthouse/axe: axe_coreAccessibilityUnitTestsPass>=98 required before sign-off; current synthetic
  fixture scores 15 of 20 component checks clean (75%), so sign-off is withheld.
- AnalyticsSnapshotPlanned=true: analytics snapshot is planned but contains no external-server claim.
- pytest: `pytest tests/test_audit_visual_and_keyboard_regressions.py`
  (suite id `tests::audit_visual_and_keyboard_regressions`).
- Hashed page baseline: `accessibility_audit/baseline.sha256` pins the fixture and this report.
- Failures-as-feedback: every failing check maps to a defect entry above with severity and component id.

ParityChecked>=for_platform_key_component
WCAG_AAReport=false
ProductDescriptionsChanged=false
