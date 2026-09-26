package main

import (
	"strings"
	"testing"

	"github.com/router-for-me/CLIProxyAPI/v7/sdk/pluginapi"
	"github.com/tidwall/gjson"
)

func rotationHistory(priorBlocks int) []byte {
	var body strings.Builder
	body.WriteString(`{"model":"kimi-k3","messages":[{"role":"user","content":"start"}`)
	for range priorBlocks {
		body.WriteString(`,{"role":"assistant","content":"done","reasoning_content":"previous thought"},`)
		body.WriteString(`{"role":"user","content":"next"}`)
	}
	body.WriteString(`]}`)
	return []byte(body.String())
}

func TestConfigPrefillRotatesWithPriorThinkingBlocks(t *testing.T) {
	cfg := mustConfig(t, "reasoning_prefill: first | second | third")
	for priorBlocks, want := range []string{"first", "second", "third", "first", "second"} {
		got := transform(cfg, "openai", "kimi-k3", rotationHistory(priorBlocks))
		if prefill := lastMessage(t, got.Body).Get("reasoning_content").String(); prefill != want {
			t.Errorf("%d prior blocks: prefill = %q, want %q", priorBlocks, prefill, want)
		}
	}
	// Selection is derived from the request, so a retry and an unrelated
	// session cannot advance a shared counter.
	for range 2 {
		got := transform(cfg, "openai", "kimi-k3", rotationHistory(1))
		if prefill := lastMessage(t, got.Body).Get("reasoning_content").String(); prefill != "second" {
			t.Fatalf("retry must select second again: %q", prefill)
		}
	}
}

func TestInlineTagRotatesAndIsStripped(t *testing.T) {
	cfg := mustConfig(t, "reasoning_prefill: config seed")
	body := []byte(`{"model":"kimi-k3","messages":[` +
		`{"role":"system","content":"<kimi_prefill>alpha | beta | gamma</kimi_prefill>"},` +
		`{"role":"user","content":"start"},` +
		`{"role":"assistant","content":"done","reasoning_content":"prior thought"},` +
		`{"role":"user","content":"next"}]}`)
	got := transform(cfg, "openai", "kimi-k3", body)
	if prefill := lastMessage(t, got.Body).Get("reasoning_content").String(); prefill != "beta" {
		t.Fatalf("inline tag should select second alternative: %q", prefill)
	}
	if system := gjson.GetBytes(got.Body, "messages.0.content").String(); system != "" {
		t.Fatalf("control tag leaked upstream: %q", system)
	}
}

func TestTrailingThinkPrefillRotates(t *testing.T) {
	cfg := mustConfig(t, "")
	body := []byte(`{"model":"kimi-k3","messages":[` +
		`{"role":"user","content":"start"},` +
		`{"role":"assistant","content":"done","reasoning_content":"previous thought"},` +
		`{"role":"user","content":"next"},` +
		`{"role":"assistant","content":"<think>alpha | beta | gamma</think>Visible prefix"}]}`)
	got := transform(cfg, "openai", "kimi-k3", body)
	last := lastMessage(t, got.Body)
	if last.Get("reasoning_content").String() != "beta" || last.Get("content").String() != "Visible prefix" || !last.Get("partial").Bool() {
		t.Fatalf("trailing assistant should use second thinking seed: %s", last.Raw)
	}
}

func TestTrailingReasoningContentAlsoRotates(t *testing.T) {
	cfg := mustConfig(t, "")
	body := []byte(`{"model":"kimi-k3","messages":[` +
		`{"role":"user","content":"start"},` +
		`{"role":"assistant","content":"done","reasoning_content":"previous thought"},` +
		`{"role":"user","content":"next"},` +
		`{"role":"assistant","content":"","reasoning_content":"alpha | beta"}]}`)
	last := lastMessage(t, transform(cfg, "openai", "kimi-k3", body).Body)
	if last.Get("reasoning_content").String() != "beta" || !last.Get("partial").Bool() {
		t.Fatalf("trailing reasoning should select second seed: %s", last.Raw)
	}
}

func TestRequestFieldRotates(t *testing.T) {
	cfg := mustConfig(t, "reasoning_prefill: config seed")
	body := []byte(`{"model":"kimi-k3","kimi_thinking_prefill":"first | second","messages":[` +
		`{"role":"user","content":"start"},` +
		`{"role":"assistant","content":"done","reasoning_content":"previous thought"},` +
		`{"role":"user","content":"next"}]}`)
	got := transform(cfg, "openai", "kimi-k3", body)
	if prefill := lastMessage(t, got.Body).Get("reasoning_content").String(); prefill != "second" {
		t.Fatalf("request field should select second alternative: %q", prefill)
	}
	if gjson.GetBytes(got.Body, "kimi_thinking_prefill").Exists() {
		t.Fatal("request field must not go upstream")
	}
}

func TestRotationCountsBeforePriorThinkingStrip(t *testing.T) {
	cfg := mustConfig(t, "reasoning_prefill: first | second\nprior_thinking: strip")
	got := transform(cfg, "openai", "kimi-k3", rotationHistory(1))
	if prefill := lastMessage(t, got.Body).Get("reasoning_content").String(); prefill != "second" {
		t.Fatalf("stripping history should not reset rotation: %q", prefill)
	}
	if gjson.GetBytes(got.Body, "messages.1.reasoning_content").Exists() {
		t.Fatalf("prior thinking should still be stripped: %s", got.Body)
	}
}

func TestRotationCountsEarlierThinkBlocks(t *testing.T) {
	cfg := mustConfig(t, "reasoning_prefill: first | second")
	body := []byte(`{"model":"kimi-k3","messages":[` +
		`{"role":"user","content":"start"},` +
		`{"role":"assistant","content":"<think>previous reasoning</think>done"},` +
		`{"role":"user","content":"next"}]}`)
	got := transform(cfg, "openai", "kimi-k3", body)
	if prefill := lastMessage(t, got.Body).Get("reasoning_content").String(); prefill != "second" {
		t.Fatalf("earlier <think> block should advance rotation: %q", prefill)
	}
}

func TestLegacyEchoSanitizerKnowsEachAlternative(t *testing.T) {
	first := "The first long reasoning seed for this task."
	second := "The second long reasoning seed for this task."
	cfg := mustConfig(t, "reasoning_prefill: "+first+" | "+second+"\npreserve_prefill_history: false")
	body := []byte(`{"model":"kimi-k3","messages":[` +
		`{"role":"user","content":"start"},` +
		`{"role":"assistant","content":"done","reasoning_content":"` + second + ` Now continue."},` +
		`{"role":"user","content":"next"}]}`)
	got := transform(cfg, "openai", "kimi-k3", body)
	if prior := gjson.GetBytes(got.Body, "messages.1.reasoning_content").String(); prior != "Now continue." {
		t.Fatalf("legacy mode should strip the selected alternative: %q", prior)
	}
}

func TestEmptyAlternativesDoNotInject(t *testing.T) {
	cfg := mustConfig(t, "reasoning_prefill: ' | | '")
	got := transform(cfg, "openai", "kimi-k3", rotationHistory(0))
	if n := len(gjson.GetBytes(got.Body, "messages").Array()); n != 1 {
		t.Fatalf("empty alternatives should not inject a prefill: %s", got.Body)
	}
}

func TestRotationTrimsEmptyAlternativesAndKeepsStaticText(t *testing.T) {
	for _, tc := range []struct {
		input string
		want  []string
	}{
		{"  unchanged  ", []string{"  unchanged  "}},
		{" first | | second | ", []string{"first", "second"}},
		{" | | ", nil},
	} {
		got := splitPrefillAlternatives(tc.input)
		if strings.Join(got, ",") != strings.Join(tc.want, ",") {
			t.Errorf("splitPrefillAlternatives(%q) = %q, want %q", tc.input, got, tc.want)
		}
	}
}

func TestStaticThinkPrefillStillTrimsOuterWhitespace(t *testing.T) {
	cfg := mustConfig(t, "")
	body := []byte(`{"model":"kimi-k3","messages":[` +
		`{"role":"user","content":"start"},` +
		`{"role":"assistant","content":"<think>  unchanged  </think>"}]}`)
	last := lastMessage(t, transform(cfg, "openai", "kimi-k3", body).Body)
	if prefill := last.Get("reasoning_content").String(); prefill != "unchanged" {
		t.Fatalf("static <think> prefill should still be trimmed: %q", prefill)
	}
}

func TestRotatedSeedIsReturnedAndReplayed(t *testing.T) {
	cfg := mustConfig(t, "reasoning_prefill: first | second | third")
	first := transform(cfg, "openai", "kimi-k3", rotationHistory(0))
	req := pluginapi.ResponseTransformRequest{
		FromFormat:        "openai",
		ToFormat:          "openai-response",
		Model:             "kimi-k3",
		TranslatedRequest: first.Body,
		Body:              []byte(`{"choices":[{"message":{"role":"assistant","content":"done","reasoning_content":" thought"}}]}`),
	}
	returned := (&responseRepairer{}).repair(cfg, req)
	if reasoning := gjson.GetBytes(returned, "choices.0.message.reasoning_content").String(); reasoning != "first thought" {
		t.Fatalf("response history should contain selected seed: %q", reasoning)
	}
	second := transform(cfg, "openai", "kimi-k3", []byte(`{"model":"kimi-k3","messages":[`+
		`{"role":"user","content":"start"},`+
		`{"role":"assistant","content":"done","reasoning_content":"first thought"},`+
		`{"role":"user","content":"next"}]}`))
	if prefill := lastMessage(t, second.Body).Get("reasoning_content").String(); prefill != "second" {
		t.Fatalf("next thinking block should select second seed: %q", prefill)
	}
}
