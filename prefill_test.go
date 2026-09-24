package main

import (
	"testing"

	"github.com/tidwall/gjson"
)

func mustConfig(t *testing.T, yamlText string) config {
	t.Helper()
	cfg, errParse := parseConfig([]byte(yamlText))
	if errParse != nil {
		t.Fatalf("parseConfig: %v", errParse)
	}
	return cfg
}

func lastMessage(t *testing.T, body []byte) gjson.Result {
	t.Helper()
	return gjson.GetBytes(body, "messages.@reverse.0")
}

func TestInjectsPrefillAfterUserTurn(t *testing.T) {
	cfg := mustConfig(t, "reasoning_prefill: I should continue the story.")
	body := []byte(`{"model":"kimi-k3","messages":[{"role":"user","content":"hi"}]}`)

	got := transform(cfg, "openai", "kimi-k3", body)

	last := lastMessage(t, got.Body)
	if last.Get("role").String() != "assistant" || last.Get("content").String() != "" ||
		last.Get("reasoning_content").String() != "I should continue the story." || !last.Get("partial").Bool() {
		t.Fatalf("unexpected injected message: %s", last.Raw)
	}
	if !gjson.GetBytes(got.Body, "include_reasoning").Bool() {
		t.Fatal("force_thinking should set include_reasoning")
	}
}

func TestSkipsWhenPrefillEmpty(t *testing.T) {
	cfg := mustConfig(t, "")
	body := []byte(`{"model":"kimi-k3","messages":[{"role":"user","content":"hi"}]}`)

	got := transform(cfg, "openai", "kimi-k3", body)

	if got.Changed || string(got.Body) != string(body) {
		t.Fatalf("expected untouched body, got %s", got.Body)
	}
}

func TestModelFilter(t *testing.T) {
	cases := []struct {
		filter string
		models []string
		want   bool
	}{
		{"kimi,moonshot", []string{"Kimi-K3"}, true},
		{"kimi, moonshot", []string{"moonshotai/kimi-k3"}, true},
		{"kimi", []string{"claude-sonnet-4-6", "kimi-k3"}, true},
		{"kimi", []string{"glm-5"}, false},
		{"", []string{"kimi-k3"}, false},
		{" , ", []string{"kimi-k3"}, false},
	}
	for _, tc := range cases {
		if got := modelMatches(tc.filter, tc.models...); got != tc.want {
			t.Errorf("modelMatches(%q, %v) = %v, want %v", tc.filter, tc.models, got, tc.want)
		}
	}
}

func TestSkipsNonMatchingModelAndFormat(t *testing.T) {
	cfg := mustConfig(t, "reasoning_prefill: seed")
	body := []byte(`{"model":"glm-5","messages":[{"role":"user","content":"hi"}]}`)

	if got := transform(cfg, "openai", "glm-5", body); got.Changed {
		t.Fatal("non-matching model should be skipped")
	}
	if got := transform(cfg, "claude", "kimi-k3", body); got.Changed {
		t.Fatal("non-openai target format should be skipped")
	}
}

func TestThinkTransformOnTrailingAssistant(t *testing.T) {
	cfg := mustConfig(t, "reasoning_prefill: unused")
	body := []byte(`{"model":"kimi-k3","messages":[{"role":"user","content":"hi"},` +
		`{"role":"assistant","content":"  <think>I should continue.</think>\n\nOnce upon"}]}`)

	got := transform(cfg, "openai", "kimi-k3", body)

	messages := gjson.GetBytes(got.Body, "messages").Array()
	if len(messages) != 2 {
		t.Fatalf("transform must not inject a second assistant message: %s", got.Body)
	}
	last := messages[1]
	if last.Get("reasoning_content").String() != "I should continue." ||
		last.Get("content").String() != "Once upon" || !last.Get("partial").Bool() {
		t.Fatalf("unexpected transformed message: %s", last.Raw)
	}
}

func TestThinkTransformOpenBlock(t *testing.T) {
	cfg := mustConfig(t, "")
	body := []byte(`{"model":"kimi-k3","messages":[{"role":"user","content":"hi"},` +
		`{"role":"assistant","content":"<think>I should"}]}`)

	last := lastMessage(t, transform(cfg, "openai", "kimi-k3", body).Body)

	if last.Get("reasoning_content").String() != "I should" || last.Get("content").String() != "" {
		t.Fatalf("unexpected transformed message: %s", last.Raw)
	}
}

func TestTrailingAssistantWithoutThinkIsLeftAlone(t *testing.T) {
	cfg := mustConfig(t, "reasoning_prefill: seed")
	body := []byte(`{"model":"kimi-k3","messages":[{"role":"user","content":"hi"},` +
		`{"role":"assistant","content":"Once upon"}]}`)

	if got := transform(cfg, "openai", "kimi-k3", body); got.Changed {
		t.Fatalf("expected untouched body, got %s", got.Body)
	}
}

func TestTrailingReasoningContentMarkedPartial(t *testing.T) {
	cfg := mustConfig(t, "")
	body := []byte(`{"model":"kimi-k3","messages":[{"role":"user","content":"hi"},` +
		`{"role":"assistant","content":"","reasoning_content":"Let me think"}]}`)

	last := lastMessage(t, transform(cfg, "openai", "kimi-k3", body).Body)

	if !last.Get("partial").Bool() || last.Get("reasoning_content").String() != "Let me think" {
		t.Fatalf("unexpected message: %s", last.Raw)
	}
}

func TestInlineTagOverridesAndIsStripped(t *testing.T) {
	cfg := mustConfig(t, "reasoning_prefill: default seed")
	body := []byte(`{"model":"kimi-k3","messages":[` +
		`{"role":"system","content":"Be nice.<kimi_prefill>The user is testing me.</kimi_prefill>"},` +
		`{"role":"user","content":[{"type":"text","text":"hi <kimi_prefill>Actually, I will be terse.</kimi_prefill>"}]}]}`)

	got := transform(cfg, "openai", "kimi-k3", body)

	if gjson.GetBytes(got.Body, "messages.0.content").String() != "Be nice." {
		t.Fatalf("system tag not stripped: %s", got.Body)
	}
	if gjson.GetBytes(got.Body, "messages.1.content.0.text").String() != "hi " {
		t.Fatalf("user tag not stripped: %s", got.Body)
	}
	if last := lastMessage(t, got.Body); last.Get("reasoning_content").String() != "Actually, I will be terse." {
		t.Fatalf("last inline tag should win: %s", last.Raw)
	}
}

func TestSelfClosingInlineTagDisablesInjection(t *testing.T) {
	cfg := mustConfig(t, "reasoning_prefill: default seed")
	body := []byte(`{"model":"kimi-k3","messages":[{"role":"user","content":"hi<kimi_prefill/>"}]}`)

	got := transform(cfg, "openai", "kimi-k3", body)

	if n := len(gjson.GetBytes(got.Body, "messages").Array()); n != 1 {
		t.Fatalf("expected no injection, got %d messages", n)
	}
	if gjson.GetBytes(got.Body, "messages.0.content").String() != "hi" {
		t.Fatalf("tag not stripped: %s", got.Body)
	}
}

func TestRequestFieldOverridesAndIsRemoved(t *testing.T) {
	cfg := mustConfig(t, "reasoning_prefill: default seed")
	body := []byte(`{"model":"kimi-k3","kimi_thinking_prefill":"field seed","messages":[{"role":"user","content":"hi"}]}`)

	got := transform(cfg, "openai", "kimi-k3", body)

	if gjson.GetBytes(got.Body, "kimi_thinking_prefill").Exists() {
		t.Fatal("request field must be removed before sending upstream")
	}
	if last := lastMessage(t, got.Body); last.Get("reasoning_content").String() != "field seed" {
		t.Fatalf("unexpected prefill: %s", last.Raw)
	}
}

func TestRequestFieldFalseDisables(t *testing.T) {
	cfg := mustConfig(t, "reasoning_prefill: default seed")
	body := []byte(`{"model":"kimi-k3","kimi_thinking_prefill":false,"messages":[{"role":"user","content":"hi"}]}`)

	got := transform(cfg, "openai", "kimi-k3", body)

	if gjson.GetBytes(got.Body, "kimi_thinking_prefill").Exists() {
		t.Fatal("request field must be removed")
	}
	if n := len(gjson.GetBytes(got.Body, "messages").Array()); n != 1 {
		t.Fatalf("expected no injection, got %d messages", n)
	}
}

func TestSkipWithTools(t *testing.T) {
	body := []byte(`{"model":"kimi-k3","tools":[{"type":"function","function":{"name":"f"}}],` +
		`"messages":[{"role":"user","content":"hi<kimi_prefill>x</kimi_prefill>"}]}`)

	skip := transform(mustConfig(t, "reasoning_prefill: seed\nskip_with_tools: true"), "openai", "kimi-k3", body)
	if n := len(gjson.GetBytes(skip.Body, "messages").Array()); n != 1 {
		t.Fatal("skip_with_tools should prevent injection")
	}
	if gjson.GetBytes(skip.Body, "messages.0.content").String() != "hi" {
		t.Fatal("inline tag should still be stripped when skipping")
	}

	allow := transform(mustConfig(t, "reasoning_prefill: seed"), "openai", "kimi-k3", body)
	if n := len(gjson.GetBytes(allow.Body, "messages").Array()); n != 2 {
		t.Fatal("tools should be allowed by default")
	}
}

func TestSkipWithJSONSchema(t *testing.T) {
	cfg := mustConfig(t, "reasoning_prefill: seed")
	body := []byte(`{"model":"kimi-k3","response_format":{"type":"json_schema"},"messages":[{"role":"user","content":"hi"}]}`)

	if got := transform(cfg, "openai", "kimi-k3", body); got.Changed {
		t.Fatal("structured output requests should be skipped")
	}
}

func TestForceThinkingRemovesDisablers(t *testing.T) {
	cfg := mustConfig(t, "reasoning_prefill: seed")
	body := []byte(`{"model":"kimi-k3","reasoning_effort":"none","chat_template_kwargs":{"thinking":false},` +
		`"thinking":{"type":"disabled"},"messages":[{"role":"user","content":"hi"}]}`)

	got := transform(cfg, "openai", "kimi-k3", body).Body

	if gjson.GetBytes(got, "reasoning_effort").Exists() || gjson.GetBytes(got, "chat_template_kwargs.thinking").Exists() {
		t.Fatalf("thinking disablers not removed: %s", got)
	}
	if gjson.GetBytes(got, "thinking.type").String() != "enabled" {
		t.Fatalf("thinking.type not enabled: %s", got)
	}
}

func TestForceThinkingOffLeavesParams(t *testing.T) {
	cfg := mustConfig(t, "reasoning_prefill: seed\nforce_thinking: false")
	body := []byte(`{"model":"kimi-k3","reasoning_effort":"none","messages":[{"role":"user","content":"hi"}]}`)

	got := transform(cfg, "openai", "kimi-k3", body).Body

	if gjson.GetBytes(got, "reasoning_effort").String() != "none" || gjson.GetBytes(got, "include_reasoning").Exists() {
		t.Fatalf("force_thinking=false should not touch params: %s", got)
	}
}

func TestPriorThinkingStrip(t *testing.T) {
	cfg := mustConfig(t, "prior_thinking: strip\ninject: false")
	body := []byte(`{"model":"kimi-k3","messages":[{"role":"user","content":"a"},` +
		`{"role":"assistant","content":"<think>old</think> answer","reasoning_content":"old"},` +
		`{"role":"user","content":"b"}]}`)

	got := transform(cfg, "openai", "kimi-k3", body).Body

	prior := gjson.GetBytes(got, "messages.1")
	if prior.Get("reasoning_content").Exists() || prior.Get("content").String() != "answer" {
		t.Fatalf("prior thinking not stripped: %s", prior.Raw)
	}
}

func TestPriorThinkingExtract(t *testing.T) {
	cfg := mustConfig(t, "prior_thinking: extract")
	body := []byte(`{"model":"kimi-k3","messages":[{"role":"user","content":"a"},` +
		`{"role":"assistant","content":"<think>old</think>answer"},{"role":"user","content":"b"}]}`)

	got := transform(cfg, "openai", "kimi-k3", body).Body

	prior := gjson.GetBytes(got, "messages.1")
	if prior.Get("reasoning_content").String() != "old" || prior.Get("content").String() != "answer" {
		t.Fatalf("prior thinking not extracted: %s", prior.Raw)
	}
}

func TestExtraBodyMergedOnlyWhenInjected(t *testing.T) {
	cfg := mustConfig(t, "reasoning_prefill: seed\nextra_body:\n  chat_template_kwargs.thinking: true\n  top_p: 0.95")
	body := []byte(`{"model":"kimi-k3","messages":[{"role":"user","content":"hi"}]}`)

	got := transform(cfg, "openai", "kimi-k3", body).Body

	if !gjson.GetBytes(got, "chat_template_kwargs.thinking").Bool() || gjson.GetBytes(got, "top_p").Float() != 0.95 {
		t.Fatalf("extra_body not merged: %s", got)
	}

	skipped := transform(cfg, "openai", "glm-5", []byte(`{"model":"glm-5","messages":[{"role":"user","content":"hi"}]}`)).Body
	if gjson.GetBytes(skipped, "top_p").Exists() {
		t.Fatal("extra_body must not apply to skipped requests")
	}
}

func TestPreservesUnknownMessageFieldsAndNumbers(t *testing.T) {
	cfg := mustConfig(t, "reasoning_prefill: seed")
	body := []byte(`{"model":"kimi-k3","messages":[{"role":"user","content":"hi","name":"bob","weight":12345678901234567890}]}`)

	got := transform(cfg, "openai", "kimi-k3", body).Body

	first := gjson.GetBytes(got, "messages.0")
	if first.Get("name").String() != "bob" || first.Get("weight").Raw != "12345678901234567890" {
		t.Fatalf("message fields not preserved: %s", first.Raw)
	}
}

func TestInvalidConfig(t *testing.T) {
	for _, bad := range []string{"prior_thinking: sometimes", "inline_tag: 'a b'", "request_field: 'x y'", "inject: [1"} {
		if _, errParse := parseConfig([]byte(bad)); errParse == nil {
			t.Errorf("expected error for %q", bad)
		}
	}
}

func TestTransformIsIdempotent(t *testing.T) {
	cfg := mustConfig(t, "reasoning_prefill: seed")
	bodies := [][]byte{
		[]byte(`{"model":"kimi-k3","messages":[{"role":"user","content":"hi"}]}`),
		[]byte(`{"model":"kimi-k3","messages":[{"role":"user","content":"hi"},{"role":"assistant","content":"<think>go on"}]}`),
		[]byte(`{"model":"kimi-k3","kimi_thinking_prefill":"x","messages":[{"role":"user","content":"hi<kimi_prefill>y</kimi_prefill>"}]}`),
	}
	for _, body := range bodies {
		once := transform(cfg, "openai", "kimi-k3", body).Body
		twice := transform(cfg, "openai", "kimi-k3", once).Body
		if string(once) != string(twice) {
			t.Errorf("not idempotent:\n once: %s\ntwice: %s", once, twice)
		}
	}
}

func TestInlineTagInDeveloperMessage(t *testing.T) {
	cfg := mustConfig(t, "")
	body := []byte(`{"model":"kimi-k3","messages":[` +
		`{"role":"developer","content":[{"type":"text","text":"Be a poet.<kimi_prefill>I will rhyme.</kimi_prefill>"}]},` +
		`{"role":"user","content":"hi"}]}`)

	got := transform(cfg, "openai", "kimi-k3", body)

	if gjson.GetBytes(got.Body, "messages.0.content.0.text").String() != "Be a poet." {
		t.Fatalf("developer tag not stripped: %s", got.Body)
	}
	if last := lastMessage(t, got.Body); last.Get("reasoning_content").String() != "I will rhyme." {
		t.Fatalf("developer tag seed not injected: %s", last.Raw)
	}
}
