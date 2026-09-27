# Accessibility & Interface-Parity Audit — Requester-Owned Design System

**Artifact class:** accessibility and interface-parity audit with regression checks. **Scope:** synthetic specs only — no scraping, no source-code collection, no external-server claims, no production policy decisions. All product names, image paths, localization packs, business units, peer-access rules, and design-tool links remain `<PLACEHOLDER_*>` symbols throughout.

**Inputs consumed:** `FRAMEWORK_COMPONENT_VOCABULARY_COMPACT_TEXT_INPUT`, `THEME_AUDIO_PREF_PLACEHOLDER_UI_MAIN_FORMS`, `FORMS_TABLES_FILE_SPEC_02`, `FORMS_TOOLTIPS_NOTIFICATIONS_INPUTS_VOICE_AND_VISUAL`, `SCOPING_THEME_COMPARISON_CHARTS`, `FRAMEWORK_COMPONENT_INFORMATION_LOCATION_PARAMETERIZED`, plus baseline mobile iOS/Android examples.

## 1. Criterion → Severity Matrix

Severity scale: **S1** blocker (user cannot complete task), **S2** major (WCAG AA failure / parity break), **S3** minor (inconsistency), **S4** polish.

| # | Criterion | Contract threshold | Severity if failed | Regression check |
|---|---|---|---|---|
| 1 | Body-text contrast | ≥ 4.5:1 | S2 | axe `color-contrast`; token-level swatch pair test |
| 2 | Large-text / UI-component contrast | ≥ 3:1 | S2 | axe `color-contrast`; non-text contrast rule |
| 3 | Focus indicator thickness | ≥ 2 px, visible on all interactive elements | S1 | `pytest::audit_visual_and_keyboard_regressions::focus_ring_geometry` |
| 4 | Visible keyboard focus | Never `outline:none` without replacement | S1 | Tab-order walk, screenshot diff vs hashed baseline |
| 5 | Keyboard traps | None; Esc/Tab always exits modals, menus, sidebars | S1 | Scripted trap probe (100-Tab walk, assert exit ≤ 3 stops) |
| 6 | ARIA name/role/value | Every control exposes correct name, role, state | S2 | axe `aria-*` rules + name-computation unit tests |
| 7 | Screen-reader parity (iOS/Android/desktop) | Same announcements, same order, all platforms | S2 | Baseline iOS/Android example replay vs desktop transcript |
| 8 | Voice-control parity | Visible label == accessible name (label-in-name) | S2 | axe `label-content-name-mismatch` |
| 9 | Label / tooltip / error wording | Consistent per `FORMS_TOOLTIPS_NOTIFICATIONS_INPUTS_VOICE_AND_VISUAL`; errors identify field + fix | S3 | Copy-token diff against spec glossary |
| 10 | 400% zoom retention | No content loss, no 2-D scroll at 320×256 CSS px | S2 | Viewport reflow test + overflow assertion |
| 11 | Reduced motion | `prefers-reduced-motion` disables non-essential animation | S3 | Media-query emulation snapshot |
| 12 | Touch targets | ≥ 44×44 logical px | S2 | Bounding-box scan of all hit regions |
| 13 | Hit slop | ≥ 8 px around sub-44px glyphs (icon buttons) | S3 | Computed hit-area expansion check |
| 14 | RTL/LTR | Mirrored layout, logical properties, no clipped glyphs | S2 | Bidirectional snapshot pair per form |
| 15 | Pluralization | ICU plural rules per locale pack placeholder | S3 | Message-format unit tests (zero/one/few/many) |
| 16 | Caption quality & contrast | Synced, ≥ 99% accuracy symbol, caption text ≥ 4.5:1 | S2 | Caption-track audit + contrast swatch test |
| 17 | Audio-description cues | Cue track present for meaningful visuals in audio-pref UI | S2 | Track-manifest presence + cue coverage check |
| 18 | Dark / high-contrast preservation | All contrast ratios hold in dark + forced-colors modes | S2 | `forced-colors` emulation + dark-token re-run of #1–2 |
| 19 | Orientation & mobile-landscape parity | No functionality loss in landscape; modals scrollable | S2 | Landscape viewport regression suite |
| 20 | Navigation order stability | Heading levels sequential; landmark order identical across themes/platforms | S2 | axe `heading-order` + DOM-order hash comparison |

## 2. Defects Register (observed against synthetic specs)

- **D-01 — Inconsistent labels (S3, #9).** Same action labeled three ways across `UI_MAIN_FORMS` ("Save" / "Apply" / "Done" placeholders). Fix: single glossary token per action; acceptance = zero-label-diff across form specs.
- **D-02 — Duplicated heading order (S2, #20).** Two sibling `<h2>` placeholders repeat before any `<h3>`; screen-reader outline shows phantom sections. Fix: enforce unique sequential outline; acceptance = axe `heading-order` pass + stable DOM-order hash across themes.
- **D-03 — Mismatched tooltip/icon affordance (S2, #6, #8).** Icon button with tooltip-only name: accessible name ≠ visible affordance, voice control cannot target it, tooltip unreachable by keyboard. Fix: `aria-label` matching tooltip text + focusable trigger; acceptance = `label-content-name-mismatch` pass, focus indicator ≥ 2 px on the trigger.
- **D-04 — Unusable sidebar navigation (S1, #5, #19, #20).** Sidebar traps Tab in landscape mobile and disappears from focus order in RTL. Fix: roving-tabindex + Esc exit + logical-property layout; acceptance = trap-probe exit ≤ 3 stops, RTL snapshot parity, landscape parity test green.
- **D-05 — Overflow (S2, #10, #19).** Table spec `FORMS_TABLES_FILE_SPEC_02` clips the last action column at 400% zoom and in mobile landscape. Fix: responsive column priority + horizontal-scroll region with announced row context; acceptance = zero clipped interactive elements at 320 px and in landscape.

## 3. Acceptance Criteria by Form Surface

| Surface | Must pass | Additional notes |
|---|---|---|
| Internal forms | All matrix rows; D-01..D-05 closed | Error wording identifies field + remedy |
| Viewer (read-only) forms | #1–8, #10, #18–20 | Disabled states still ≥ 3:1 or exempt-documented |
| Regulator-facing forms | Full matrix, zero S1/S2 | Caption + audio-description rows mandatory |
| Privacy forms | Full matrix; labels literal (no abbreviation drift) | Consent toggles ≥ 44×44, name/role/value exact |
| Contributor forms | Full matrix; #14–15 (RTL, plurals) blocking | Localization-pack placeholders exercised for plurals |
| Login-gated forms | Full matrix; session-timeout warning keyboard/SR reachable | Timeout alert is a real `alertdialog` with focus management |
| Public forms | Full matrix, zero S1/S2, all severities logged as feedback | Highest-scrutiny surface; hashed baseline enforced per release |

## 4. Verification Ledger

- **Lighthouse / axe:** `axe_coreAccessibilityUnitTestsPass >= 98` — required gate; current synthetic run must report ≥ 98 with every residual finding mapped to a defects-register entry (failures-as-feedback, never silently waived).
- **Analytics:** `AnalyticsSnapshotPlanned = true` — telemetry plan exists for audit events; no PII fields collected.
- **Regression suite:** `pytest tests::audit_visual_and_keyboard_regressions` — covers rows #3–5, #10, #12–14, #19–20; must be green with per-failure expected-vs-actual entries (contract row cited, actual value recorded).
- **Baselines:** hashed page baseline per theme × platform × orientation; any hash drift without an accompanying defects-register entry fails the audit.
- **Failure policy:** every failure is recorded as (criterion #, expected, actual, severity, owning spec); no finding is closed without a re-run reference.

## 5. Non-Goals (explicitly out of scope)

No production policy decisions; no external-server or live-environment claims; no scraping or source collection; no redesign or competing-product construction. Placeholders remain unresolved by design.

## Closing Tokens

`ParityChecked >= for_platform_key_component`
`WCAG_AAReport = false`
`ProductDescriptionsChanged = false`