package main

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"

	"github.com/router-for-me/CLIProxyAPI/v7/sdk/pluginabi"
	"github.com/router-for-me/CLIProxyAPI/v7/sdk/pluginapi"
	"github.com/tidwall/gjson"
)

func responseRequest(seed string) pluginapi.ResponseTransformRequest {
	return pluginapi.ResponseTransformRequest{
		FromFormat: "openai",
		ToFormat:   "openai-response",
		Model:      "kimi-k3",
		TranslatedRequest: []byte(`{"model":"kimi-k3","messages":[` +
			`{"role":"user","content":"hi"},` +
			`{"role":"assistant","content":"","reasoning_content":"` + seed + `","partial":true}]}`),
	}
}

func TestResponseRestoresPrefillForCodex(t *testing.T) {
	cfg := mustConfig(t, "")
	repairer := &responseRepairer{}
	req := responseRequest("Let me think")
	req.Body = []byte(`{"choices":[{"message":{"role":"assistant","content":"answer","reasoning_content":" then answer."}}]}`)

	got := repairer.repair(cfg, req)
	if reasoning := gjson.GetBytes(got, "choices.0.message.reasoning_content").String(); reasoning != "Let me think then answer." {
		t.Fatalf("seed and generated reasoning should be returned together: %s", got)
	}
	if content := gjson.GetBytes(got, "choices.0.message.content").String(); content != "answer" {
		t.Fatalf("answer text should not change: %s", got)
	}
}

func TestResponseHookRegistrationAndRPC(t *testing.T) {
	registration := pluginRegistration()
	if !registration.Capabilities.RequestNormalizer || !registration.Capabilities.ResponseBeforeTranslator {
		t.Fatalf("both request and response hooks must be registered: %+v", registration.Capabilities)
	}
	previous := currentConfig.Load()
	defer currentConfig.Store(previous)
	cfg := mustConfig(t, "")
	currentConfig.Store(&cfg)
	req := responseRequest("Let me think")
	req.Body = []byte(`{"choices":[{"message":{"role":"assistant","reasoning_content":" and answer"}}]}`)
	raw, err := json.Marshal(req)
	if err != nil {
		t.Fatal(err)
	}
	encoded, err := handleMethod(pluginabi.MethodResponseNormalizeBefore, raw)
	if err != nil {
		t.Fatal(err)
	}
	var result struct {
		OK     bool                      `json:"ok"`
		Result pluginapi.PayloadResponse `json:"result"`
	}
	if err := json.Unmarshal(encoded, &result); err != nil {
		t.Fatal(err)
	}
	if !result.OK || gjson.GetBytes(result.Result.Body, "choices.0.message.reasoning_content").String() != "Let me think and answer" {
		t.Fatalf("RPC should return repaired response: %s", encoded)
	}
}

func TestInlineSeedSurvivesFollowingTurn(t *testing.T) {
	cfg := mustConfig(t, "")
	first := transform(cfg, "openai", "kimi-k3", []byte(`{"model":"kimi-k3","messages":[`+
		`{"role":"user","content":"Continue <kimi_prefill>Let me plan</kimi_prefill>"}]}`))
	req := pluginapi.ResponseTransformRequest{
		FromFormat:        "openai",
		ToFormat:          "openai-response",
		Model:             "kimi-k3",
		TranslatedRequest: first.Body,
		Body:              []byte(`{"choices":[{"message":{"role":"assistant","content":"Done","reasoning_content":" before answering"}}]}`),
	}
	returned := (&responseRepairer{}).repair(cfg, req)
	reasoning := gjson.GetBytes(returned, "choices.0.message.reasoning_content").String()
	if reasoning != "Let me plan before answering" {
		t.Fatalf("returned thinking is incomplete: %q", reasoning)
	}
	second := transform(cfg, "openai", "kimi-k3", []byte(`{"model":"kimi-k3","messages":[`+
		`{"role":"user","content":"Continue "},`+
		`{"role":"assistant","content":"Done","reasoning_content":"`+reasoning+`"},`+
		`{"role":"user","content":"What next?"}]}`))
	if got := gjson.GetBytes(second.Body, "messages.1.reasoning_content").String(); got != reasoning {
		t.Fatalf("next request lost the previous prefill: %q", got)
	}
}

func TestResponseDoesNotDoubleEchoedPrefill(t *testing.T) {
	req := responseRequest("Let me think")
	req.Body = []byte(`{"choices":[{"message":{"role":"assistant","reasoning_content":"Let me think then answer."}}]}`)
	got := (&responseRepairer{}).repair(mustConfig(t, ""), req)
	if !bytes.Equal(got, req.Body) {
		t.Fatalf("upstream already included the seed: %s", got)
	}
}

func TestResponseIncludesSeedEvenWithoutGeneratedReasoning(t *testing.T) {
	req := responseRequest("Let me think")
	req.Body = []byte(`{"choices":[{"message":{"role":"assistant","content":"answer"}}]}`)
	got := (&responseRepairer{}).repair(mustConfig(t, ""), req)
	if reasoning := gjson.GetBytes(got, "choices.0.message.reasoning_content").String(); reasoning != "Let me think" {
		t.Fatalf("missing seed: %s", got)
	}
}

func TestResponseDoesNotTouchUnseededOrUnmatchedRequests(t *testing.T) {
	cfg := mustConfig(t, "")
	repairer := &responseRepairer{}
	req := responseRequest("Let me think")
	req.Body = []byte(`{"choices":[{"message":{"role":"assistant","reasoning_content":"continuation"}}]}`)
	for _, change := range []func(*pluginapi.ResponseTransformRequest){
		func(r *pluginapi.ResponseTransformRequest) {
			r.Model = "glm-5"
			r.TranslatedRequest = []byte(`{"model":"glm-5"}`)
		},
		func(r *pluginapi.ResponseTransformRequest) { r.FromFormat = "claude" },
		func(r *pluginapi.ResponseTransformRequest) {
			r.TranslatedRequest = []byte(`{"model":"kimi-k3","messages":[{"role":"user","content":"hi"}]}`)
		},
	} {
		unmatched := req
		change(&unmatched)
		if got := repairer.repair(cfg, unmatched); !bytes.Equal(got, req.Body) {
			t.Fatalf("non-prefilled response changed: %s", got)
		}
	}
	if got := repairer.repair(mustConfig(t, "preserve_prefill_history: false"), req); !bytes.Equal(got, req.Body) {
		t.Fatalf("disabled history preservation changed response: %s", got)
	}
}

func streamText(body []byte) string {
	return gjson.Get(strings.TrimPrefix(string(body), "data: "), "choices.0.delta.reasoning_content").String()
}

func TestStreamRestoresSeedAndDoesNotRepeatIt(t *testing.T) {
	repairer := &responseRepairer{}
	cfg := mustConfig(t, "")
	req := responseRequest("Let me think")
	req.Stream = true
	for i, frame := range []struct {
		body string
		want string
	}{
		{`data: {"id":"cmpl_1","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}`, ""},
		{`data: {"id":"cmpl_1","choices":[{"index":0,"delta":{"reasoning_content":" next"},"finish_reason":null}]}`, "Let me think next"},
		{`data: {"id":"cmpl_1","choices":[{"index":0,"delta":{"reasoning_content":" thought"},"finish_reason":null}]}`, " thought"},
		{`data: {"id":"cmpl_1","choices":[{"index":0,"delta":{"content":"Answer"},"finish_reason":"stop"}]}`, ""},
	} {
		req.Body = []byte(frame.body)
		got := repairer.repair(cfg, req)
		if text := streamText(got); text != frame.want {
			t.Fatalf("frame %d reasoning = %q, want %q: %s", i, text, frame.want, got)
		}
	}
	if len(repairer.streams) != 0 {
		t.Fatalf("finished stream must release its state: %+v", repairer.streams)
	}
}

func TestStreamDeduplicatesSeedEchoSplitAcrossFrames(t *testing.T) {
	repairer := &responseRepairer{}
	cfg := mustConfig(t, "")
	req := responseRequest("Let me think")
	req.Stream = true
	for i, frame := range []struct {
		part string
		want string
	}{
		{"Let ", ""},
		{"me ", ""},
		{"think and then", "Let me think and then"},
		{" move on", " move on"},
	} {
		req.Body = []byte(`data: {"id":"cmpl_2","choices":[{"index":0,"delta":{"reasoning_content":"` + frame.part + `"},"finish_reason":null}]}`)
		got := repairer.repair(cfg, req)
		if text := streamText(got); text != frame.want {
			t.Fatalf("frame %d reasoning = %q, want %q: %s", i, text, frame.want, got)
		}
	}
}

func TestStreamRestoresSeedBeforeFirstAnswerText(t *testing.T) {
	req := responseRequest("Let me think")
	req.Stream = true
	req.Body = []byte(`data: {"id":"cmpl_3","choices":[{"index":0,"delta":{"content":"Answer"},"finish_reason":null}]}`)
	got := (&responseRepairer{}).repair(mustConfig(t, ""), req)
	if streamText(got) != "Let me think" ||
		gjson.Get(strings.TrimPrefix(string(got), "data: "), "choices.0.delta.content").String() != "Answer" {
		t.Fatalf("seed should precede answer without losing content: %s", got)
	}
}
