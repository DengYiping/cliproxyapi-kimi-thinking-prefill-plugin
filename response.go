package main

import (
	"bytes"
	"crypto/sha256"
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/router-for-me/CLIProxyAPI/v7/sdk/pluginapi"
	"github.com/tidwall/gjson"
	"github.com/tidwall/sjson"
)

// responseRepairer keeps only the short-lived prefix comparison needed for
// streaming responses. The seed itself comes from the actual upstream request,
// not from mutable config or a cross-request lookup.
type responseRepairer struct {
	mu      sync.Mutex
	streams map[string]*prefillStream
}

type prefillStream struct {
	seed     string
	pending  string
	inserted bool
	updated  time.Time
}

var replyRepairer = &responseRepairer{streams: make(map[string]*prefillStream)}

func responsePrefill(cfg config, req pluginapi.ResponseTransformRequest) string {
	if !cfg.PreservePrefillHistory || !strings.EqualFold(req.FromFormat, "openai") ||
		!modelMatches(cfg.ModelFilter, req.Model, gjson.GetBytes(req.TranslatedRequest, "model").String()) {
		return ""
	}
	last := gjson.GetBytes(req.TranslatedRequest, "messages.@reverse.0")
	if last.Get("role").String() != "assistant" || !last.Get("partial").Bool() {
		return ""
	}
	return last.Get("reasoning_content").String()
}

// repair runs before the host translates the OpenAI response to the client's
// protocol. The host then builds its reasoning item from the complete text,
// including for streaming Responses API clients such as Codex.
func (r *responseRepairer) repair(cfg config, req pluginapi.ResponseTransformRequest) []byte {
	seed := responsePrefill(cfg, req)
	if seed == "" {
		return req.Body
	}
	if req.Stream {
		return r.repairStream(req, seed)
	}
	return repairNonStream(req.Body, seed)
}

func repairNonStream(body []byte, seed string) []byte {
	message := gjson.GetBytes(body, "choices.0.message")
	if !message.Exists() || message.Get("role").String() != "assistant" {
		return body
	}
	reasoning := message.Get("reasoning_content").String()
	if reasoning == "" {
		reasoning = message.Get("reasoning").String()
	}
	if strings.HasPrefix(reasoning, seed) {
		return body
	}
	updated, err := sjson.SetBytes(body, "choices.0.message.reasoning_content", seed+reasoning)
	if err != nil {
		return body
	}
	return updated
}

func streamKey(req pluginapi.ResponseTransformRequest, chunk gjson.Result) string {
	// OpenAI chat-completions IDs identify a stream even when many requests have
	// the same prompt. A request hash is only a fallback for providers omitting IDs.
	if id := chunk.Get("id").String(); id != "" {
		return "id:" + id
	}
	hash := sha256.Sum256(req.TranslatedRequest)
	return fmt.Sprintf("request:%x", hash)
}

func (r *responseRepairer) repairStream(req pluginapi.ResponseTransformRequest, seed string) []byte {
	line := bytes.TrimSpace(req.Body)
	if !bytes.HasPrefix(line, []byte("data:")) {
		return req.Body
	}
	data := bytes.TrimSpace(line[len("data:"):])
	if bytes.Equal(data, []byte("[DONE]")) {
		r.mu.Lock()
		// [DONE] has no response ID; find this request's stream by its fallback
		// key only when the provider omitted IDs. ID-bearing streams are expired.
		hash := sha256.Sum256(req.TranslatedRequest)
		delete(r.streams, fmt.Sprintf("request:%x", hash))
		r.mu.Unlock()
		return req.Body
	}
	if !gjson.ValidBytes(data) {
		return req.Body
	}
	chunk := gjson.ParseBytes(data)
	choice := chunk.Get("choices.0")
	if !choice.Exists() || choice.Get("index").Int() != 0 {
		return req.Body
	}
	key := streamKey(req, chunk)
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.streams == nil {
		r.streams = make(map[string]*prefillStream)
	}
	state := r.streams[key]
	if state == nil || state.seed != seed {
		// Requests aborted without [DONE] cannot leave unbounded state behind.
		for oldKey, oldState := range r.streams {
			if time.Since(oldState.updated) > 10*time.Minute {
				delete(r.streams, oldKey)
			}
		}
		state = &prefillStream{seed: seed}
		r.streams[key] = state
	}
	state.updated = time.Now()
	if state.inserted {
		if choice.Get("finish_reason").String() != "" {
			delete(r.streams, key)
		}
		return req.Body
	}
	delta := choice.Get("delta")
	reasoning := delta.Get("reasoning_content").String()
	if reasoning == "" {
		reasoning = delta.Get("reasoning").String()
	}
	toolCalls := delta.Get("tool_calls")
	hasToolCalls := toolCalls.IsArray() && len(toolCalls.Array()) > 0
	finishing := choice.Get("finish_reason").String() != ""
	if reasoning == "" && state.pending == "" && delta.Get("content").String() == "" &&
		!hasToolCalls && !finishing {
		return req.Body
	}

	candidate := state.pending + reasoning
	// A provider may echo the prefill over several tiny deltas. Hold those
	// deltas until they either equal the seed or diverge, then emit one complete
	// reasoning delta. This avoids doubling an echoed seed.
	if reasoning != "" && strings.HasPrefix(seed, candidate) && len(candidate) < len(seed) &&
		delta.Get("content").String() == "" && !hasToolCalls && !finishing {
		state.pending = candidate
		updated, err := sjson.SetBytes(data, "choices.0.delta.reasoning_content", "")
		if err != nil {
			return req.Body
		}
		if delta.Get("reasoning").Exists() {
			updated, _ = sjson.DeleteBytes(updated, "choices.0.delta.reasoning")
		}
		return append([]byte("data: "), updated...)
	}

	complete := candidate
	if !strings.HasPrefix(candidate, seed) {
		complete = seed + candidate
	}
	updated, err := sjson.SetBytes(data, "choices.0.delta.reasoning_content", complete)
	if err != nil {
		return req.Body
	}
	if delta.Get("reasoning").Exists() {
		updated, _ = sjson.DeleteBytes(updated, "choices.0.delta.reasoning")
	}
	state.pending = ""
	state.inserted = true
	if finishing {
		delete(r.streams, key)
	}
	return append([]byte("data: "), updated...)
}
