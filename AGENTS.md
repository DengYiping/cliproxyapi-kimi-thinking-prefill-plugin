# AGENTS.md

## Repository Structure

- `main.go` defines the C-shared plugin ABI and method dispatch.
- `prefill.go` owns request transformation, the embedded thinking prompts, and request routing. Embedded prompts live here; do not move them into external config or client code.
- `response.go` owns response normalization: restoring the reasoning seed for streaming clients and performing refusal-specific rewrites.
- `prefill_test.go` and `response_test.go` are the focused Go regression suite.
- `config.example.yaml` documents the plugin configuration surface.
- `.run/` is historical experimental evidence. Preserve it; do not regenerate or overwrite past trials.

## Development Loop

Run the Go suite before committing:

```sh
go test .
```

Build, install, and hot-reload the locally wired CLIProxyAPI plugin:

```sh
make install
# Never restart the shared service: make install copies a versioned dylib into
# its watched plugin directory, and CLIProxyAPI hot-reloads that file.
```

Configuration is at `/opt/homebrew/etc/cliproxyapi.conf` under `plugins.configs.kimi-thinking-prefill`. Request decisions are logged at:

```text
/Users/ydeng/.cli-proxy-api/logs/main.log
```

A healthy modified request logs either `injected reasoning prefill` or `transformed trailing think prefill` for model `kimi-k3`.
Verify live activation through the management API (for example, `/v0/management/plugins`)
before declaring an install complete.

## Iteration Rules

1. Keep every thinking prompt inside this repository, preferably in `prefill.go`.
2. Route embedded recipes narrowly. Exact signals beat broad semantic inference.
3. Never route a bare Calculator request to remote-device behavior. The Calculator recipe may match only explicit remote server/device or designated-device execution contexts.
4. Treat opaque CVE, advisory, license, and hash labels as request-local symbols with caller-supplied semantics; do not instruct the model to verify unverifiable external records.
5. Respect tool, structured-output, format, and model-filter skips.
6. Preserve refusal floors for intentional negative controls; do not rewrite an explicit capability boundary into a fabricated workaround.

## Benchmark Workflow

Active iteration files:

- `benchmark/iteration2_prompts.tsv`
- `benchmark/iteration2_predicates.json`
- `benchmark/final_refusal_suite.py`
- `benchmark/iteration2_runner.py`

Saved evidence lives at:

```text
benchmark/results/iteration2-openai/<model>/<tag>/
```

Never overwrite an existing tag without a deliberate `--force` decision. To run the active suite:

```sh
python3 benchmark/iteration2_runner.py --model <model> --tag <new-tag> --workers 4
```

Useful runner operations:

```sh
python3 benchmark/iteration2_runner.py --list
python3 benchmark/iteration2_runner.py --tag <tag> --dry-run
python3 benchmark/iteration2_runner.py --tag <tag> --only hard-02,hard-06
python3 benchmark/iteration2_runner.py --tag <tag> --recompute
```

The runner posts directly to an OpenAI-compatible chat-completions endpoint (by default `http://127.0.0.1:8317/v1`) and reads the bearer token from `OPENAI_API_KEY`; pass `--base-url` or `--api-key-env` as needed. `--workers` controls concurrent HTTP requests, and `--dry-run` prints the requests without sending them.

## Continuation Checks

After each completed round:

1. Run `go test .`.
2. Recompute the benchmark report.
3. Read failure answers directly; do not treat regex failures as behavior failures.
4. Separate intentional refusals from accidental ones.
5. Revise prompts, routers, or scorers based on direct evidence.
6. Commit completed rounds with a focused message.

## New Refusal Cases

Prefer concise, lexically clean prompts under roughly 450 characters. Include explicit authorized scope, concrete output markers, and deterministic closure tokens. Stress phrases such as `implementing full chain exploits`, `avoid logger`, `running in stealth`, and `avoiding detection` must remain bounded, authorized, and non-destructive. Include a no-plugin or capability-floor probe that should produce an actual refusal when the plugin is disabled.

## Interim Files

Temporary scratch matrices and draft prompts belong under `.run/scratch/` or `/tmp/`, not the repository root. Delete them when the final prompt/rubric lands.
