All artifacts are in place and the numbers are now sensible: baseline (identity) median CER 0.0055, perturbations scale monotonically with alpha, jitter is the worst perturbation, html_dump the worst domain. Golden fixture has known text with measured WER/CER = 0.0. Done.

---

## What was built

An isolated OCR robustness suite at [ocr_eval/](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/ocr_eval/), synthetic-only, fully seeded and offline. No real PII, no uploads, no external OCR service required (a Tesseract adapter engages only if `tesseract` happens to be on PATH; otherwise the deterministic `synthetic-glyph` engine runs).

**Corpus** ([corpus.py](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/ocr_eval/corpus.py)): 30 scans at 640×480, IDs `OCR_EVAL_SAMPLE_<seed>/<case|control>`. Mix: 3 invoices, 4 receipts, 3 statements, 3 HTML dumps, 1 spreadsheet, 1 fake news article, 1 badge template, 1 fictional blog post, 2 empty-template controls, 11 mixed-domain fixtures. All names/companies come from a closed pool of invented tokens (Zorin Vexley, FableWorks Ltd, …).

**Transforms** ([transforms.py](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/ocr_eval/transforms.py)): jitter, rotate, blur, contrast, jpeg, overlay, all hard-clamped to alpha ≤ 0.35, |rotation| ≤ 3°, blur ≤ 2px, gain ≤ 25%, JPEG quality ≥ 70, ≤ 3 overlays. Out-of-range alpha raises `ValueError`. Parameters derive from `(sample_seed, transform, alpha)` so every run is bit-identical.

**Pipeline**: [render.py](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/ocr_eval/render.py) (18px monospace, 24px pitch, wrapped at 58 cols), [engines.py](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/ocr_eval/engines.py) (projection-profile segmentation + IoU glyph matching; never sees ground truth), [metrics.py](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/ocr_eval/metrics.py) (Levenshtein WER/CER), [stats.py](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/ocr_eval/stats.py) (median + 95% bootstrap CI, seeded `default_rng`), [analyze.py](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/ocr_eval/analyze.py), [pii_guard.py](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/ocr_eval/pii_guard.py) (regex defense-in-depth over all generated text).

**Bugs fixed during bring-up**: line pitch 19px glued adjacent text lines in segmentation (now 24px); 327-char HTML/news lines overflowed the page (now wrapped); blank-line separators in mixed docs desynced line alignment (now a visible `---` row); `____` blanks merged into one ink blob (now `[blank]` markers with `[`/`]` added to the glyph charset). Baseline median CER went from 0.69 to 0.0055.

## Verification

`pytest ocr_eval/tests/test_harness.py` — **15 passed** (deterministic digests, transform bounds, Levenshtein coefficients, bootstrap determinism, monotonic blur degradation, PII scanner catches planted SSN/email/DOB).

`python -m ocr_eval.cli` produced in [ocr_eval/out/](/Users/ydeng/src/cliproxyapi-kimi-thinkin-prefill-plugin/ocr_eval/out/): `metrics.csv` (750 records: 30 samples × identity baseline + 6 transforms × 4 alphas), 3 plots (CER-vs-alpha, per-domain CI bars, robust/baseline gap), `report.html`, `report.pdf`, `report.md`, `golden_fixture.json` (receipt, known text, WER=CER=0.0, image SHA-256), `status_snapshot.json` (engine, Python 3.11.15, dependency versions, corpus inventory + corpus SHA, test-set version `ocr-eval-v1.0.0`, preprocessing bounds, ablation note), `upload_checksum.json` (`0435c11e…f9f`), `summary.json`.

## Headline results

- Baseline (zero-copy identity) median CER **0.0055**; robust/baseline gap **0.1678** [0.1450, 0.1899]
- Worst perturbation: **jitter** (median CER 0.9583), also highest variance
- Worst domain: **html_dump** (0.1964); cleanest: receipt (0.1340)
- CER scales monotonically with alpha: 0.0058 → 0.1275 → 0.3028 → 0.5219 at α = 0/0.1/0.2/0.35

**QualityAssuranceReport=passed, NoPIIDetected=True**