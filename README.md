# kimi-thinking-prefill (CLIProxyAPI plugin)

A [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) request-normalizer plugin that seeds Kimi's
chain of thought with partial prefill. It is a proxy-side port of the SillyTavern extension
[KimiThinkingPrefill](https://github.com/Rurijian/KimiThinkingPrefill), so every client behind the proxy
gets it: OpenAI SDKs, Claude Code through a model alias, and others.

For a matching request, the plugin appends this message to the upstream chat-completions payload:

```json
{"role": "assistant", "content": "", "reasoning_content": "<your seed>", "partial": true}
```

Kimi then continues its reasoning from the seed instead of starting fresh.

## How it works

The plugin declares the `request_normalizer` capability. CLIProxyAPI calls it after translating a request
into the upstream protocol, so it always sees an OpenAI chat-completions body, whatever the client spoke:

1. Only requests with target format `openai` and a model that matches `model_filter` are touched.
2. Per-request overrides (inline tag, request field) are read and stripped.
3. Structured-output requests are skipped, and tool requests too if `skip_with_tools` is set.
4. `prior_thinking` is applied to earlier assistant turns.
5. If the last message is an assistant prefill, it is transformed. Otherwise the seed is injected.
6. `force_thinking` removes params that disable thinking, and `extra_body` is merged in.

## Requirements

- CLIProxyAPI with plugin ABI 1 and RPC schema ≤ 6. This plugin is built against `v7.3.5`.
  Rebuild after upgrading CLIProxyAPI if plugin loading fails.
- Go 1.26+ with cgo (`brew install go`).
- An upstream that honors `partial` and `reasoning_content`: the Moonshot API, OpenRouter (Moonshot provider),
  or vLLM/SGLang serving Kimi (for example via LiteLLM `hosted_vllm`).

## Build and install

```bash
make test
make install                     # copies to ~/.cli-proxy-api/plugins/<goos>/<goarch>/
make install PLUGINS_DIR=/path   # or somewhere else
```

Then merge [`config.example.yaml`](config.example.yaml) into your CLIProxyAPI config and restart it:

```bash
brew services restart cliproxyapi
```

Use an absolute or `~/` path for `plugins.dir`. A relative path resolves against the process working
directory, which is not useful for a launchd/brew service. The artifact file name must be
`kimi-thinking-prefill.<dylib|so|dll>`, because the file name is the plugin ID.

Changes to the plugin's settings hot-reload with the config file. Replacing the `.dylib` requires a restart.

## Configuration

All keys live under `plugins.configs.kimi-thinking-prefill`. `enabled` and `priority` are host-level keys.

| Key | Default | SillyTavern equivalent | Description |
|---|---|---|---|
| `inject` | `true` | `enabled` | Master switch for injection and the trailing `<think>` transform. |
| `reasoning_prefill` | `""` | `reasoning_prefill` | Seed placed in `reasoning_content`. An empty seed disables injection unless a per-request override provides one. |
| `model_filter` | `kimi,moonshot` | `model_filter` | Comma-separated, case-insensitive substrings. Matched against the upstream model and the payload's `model`. An empty filter matches nothing. |
| `force_thinking` | `true` | `force_thinking` | On modified requests, removes `reasoning_effort: none`, `chat_template_kwargs.thinking: false`, and `thinking.type: disabled` (set to `enabled`), then sets `include_reasoning: true`. |
| `think_transform` | `true` | (always on) | Converts a trailing assistant `<think>…` prefill into `reasoning_content` + `partial`. |
| `prior_thinking` | `keep` | `send_all_thinking` | Earlier assistant turns: `keep` as sent, `strip` reasoning (saves input tokens), or `extract` leading `<think>…</think>` into `reasoning_content`. |
| `skip_with_tools` | `false` | (always skips) | Skip requests with `tools`, `tool` turns, or `tool_calls`. |
| `skip_with_json_schema` | `true` | (always skips) | Skip `response_format` `json_schema` / `json_object`. |
| `inline_tag` | `kimi_prefill` | – | Name of the per-request prompt tag (see below). Empty disables. |
| `request_field` | `kimi_thinking_prefill` | – | Name of the per-request body field (see below). Empty disables. |
| `sanitize_history` | `true` | – | Remove refusal monologues, prefill echoes, and transport notes from history; drop empty assistant turns (see below). |
| `anchor` | `true` | – | Append the verbatim user ask to a config-sourced prefill (see below). |
| `anchor_template` | (built-in) | – | Template appended when `anchor` is on; must contain `{ask}`, which is replaced with the whitespace-collapsed user ask. |
| `anchor_max_chars` | `300` | – | Cap on the verbatim ask embedded by the anchor. Asks shorter than 20 runes get no anchor. |
| `extra_body` | `{}` | – | Map of [sjson paths](https://github.com/tidwall/sjson#path-syntax) to values, merged only into requests that get a prefill. Example: `chat_template_kwargs.thinking: true`. |
| `debug_log` | `false` | `debug_log` | Logs one line per matching request, with the skip reason or the actions applied. |

The SillyTavern extension defaults `reasoning_prefill` to a roleplay seed. Here it defaults to empty, so
enabling the plugin never silently changes requests; set a seed yourself.

The settings are also declared as plugin `ConfigFields`, so the management center can show and edit them.

## Per-request control

Precedence, highest first: request field, then inline tag, then `reasoning_prefill`.

**Inline tag.** This works from any client, including Claude Code (for example, put it in `CLAUDE.md` or a
system prompt). Tags in system, developer, and user messages are removed before the request goes upstream.
If there are several, the last one wins.

```text
<kimi_prefill>The user wants a terse answer. I will reply in one sentence and</kimi_prefill>
<kimi_prefill/>   <!-- disables injection for this request -->
```

**Request field.** For OpenAI-format clients; the field is removed before the request goes upstream.

```json
{"model": "kimi-k3", "kimi_thinking_prefill": "Let me reconsider the user's constraints:", "messages": [...]}
{"model": "kimi-k3", "kimi_thinking_prefill": false, "messages": [...]}
```

**Trailing assistant prefill (SillyTavern style).** If the last message is from the assistant:

- content starting with `<think>` becomes `reasoning_content`. Anything after `</think>` stays in `content`, and `partial: true` is set.
- an assistant message with `reasoning_content` gets `partial: true`. Claude-format clients produce this when they send an assistant `thinking` block as the last turn.
- a client-supplied `partial: true` is left untouched, and so is plain text without `<think>`.

## History sanitization

With `sanitize_history: true` (the default), every matching request is cleaned before it goes upstream,
even when no prefill is injected:

- **Refusal excision.** Assistant turns whose content matches the refusal marker set (English, Russian,
  and Chinese openings and tails) are rewritten sentence by sentence: refusal sentences are cut, the rest
  is kept. A turn is dropped entirely when the refusal was the whole message, more than 70% of it, or too
  smeared across sentences to cut cleanly. This breaks the self-consistency anchor of long sessions: a
  model that has visibly refused once tends to defend that position instead of answering the next request.
  Turns carrying `tool_calls` or `function_call` are never touched.
- **Prefill echoes.** Verbatim copies of the configured `reasoning_prefill` are removed from the
  `reasoning_content` / `reasoning` fields of earlier assistant turns, so a client that echoes reasoning
  back cannot re-anchor the model on the seed text itself. Seeds shorter than 24 runes are not stripped.
- **Transport notes.** Gateway control metadata such as `[Note: model was just switched ...]` is removed
  from user messages; a user message that held only the note is dropped.
- **Empty assistant turns.** Assistant messages with no content and no payload (`tool_calls`, reasoning,
  `refusal`, `audio`) are dropped; Kimi rejects requests containing them.

Sanitization runs before the skip checks, so history is cleaned even for requests that end up skipped
(structured output, tools). The debug log line reports the counters, e.g.
`sanitized history (refusals=1 echoes=2 empty=1)`.

## Ask anchor

With `anchor: true` (the default), a config-sourced prefill gets the verbatim user ask appended through
`anchor_template`. The anchor pins the reasoning to the actual request: without it the model can drift
into a recalled template task and satisfy its instructions with invented objects. The ask is
whitespace-collapsed, capped at `anchor_max_chars` runes, and skipped entirely when shorter than 20 runes.
Per-request overrides (inline tag, request field) are used verbatim and never anchored.

## Verified behavior

Tested end to end through CLIProxyAPI v7.3.5 → LiteLLM (`hosted_vllm/moonshotai/Kimi-K3` on Baseten):

| Scenario | Result |
|---|---|
| Config seed, OpenAI client | Kimi continues the seeded thought and follows its decision. |
| Inline tag in a system prompt | Tag stripped; the tag's seed is used. |
| Inline tag in a `developer` message (Chat Completions and Responses API) or in Responses `instructions` | Tag stripped; the tag's seed is used. |
| `kimi_thinking_prefill: false` | No injection. |
| Trailing `<think>…` assistant message | Transformed; the seed is honored. |
| Claude Messages client via a `claude-sonnet-4-6` → `kimi-k3` alias, streaming | Seed honored. |
| Tools declared, or after a tool result | Prefill honored, and it can steer tool calls. |
| Non-matching model / `json_object` | Skipped. |
| Config edit while running | Hot-reloaded without restart. |

## Caveats

- **Seeds can be overruled.** Kimi follows seeds that fit the user's request, but often talks itself out of
  seeds that contradict it (for example, "the user asked for English, but I decided to write French").
- **Prefilling answer text is broken on vLLM backends.** If a trailing assistant message keeps text after
  `</think>` (or uses plain-text `partial`), the continuation still arrives. On vLLM, though, it comes back
  in `reasoning_content` with leaked template tokens (`<|close|>response<|sep|>…`), and `content` is empty.
  The cause is the upstream reasoning parser, not this plugin. Reasoning-only seeds are unaffected.
- **`reasoning_effort: none` silently discards the prefill.** This is what Claude-format requests with
  thinking disabled translate to. With `force_thinking: true` (the default), such requests are re-enabled
  and the client receives thinking blocks it did not ask for. Set `force_thinking: false` to respect the
  client's choice instead, and lose the prefill on those requests.
- Tags and the request field are only consumed for models that match `model_filter`. Other models see them as-is.
