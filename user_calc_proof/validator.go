// validator.go - paired validator for the authorized localhost fixture.
// Run modes:
//   validator basic    -> sends the approved command, expects "OK launched",
//                         then verifies Calculator (not a substitute) launched.
//   validator negative -> probes rejected command, permission denied, and
//                         malformed packet lengths; expects ERR responses.
//   validator bench    -> 100-session throughput fixture on loopback.
package main

import (
	"encoding/binary"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"strings"
	"time"
)

const addr = "127.0.0.1:18321"

func roundTrip(payload []byte, rawLen []byte) (string, error) {
	conn, err := net.DialTimeout("tcp", addr, 2*time.Second)
	if err != nil {
		return "", fmt.Errorf("unreachable local peer: %w", err)
	}
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(3 * time.Second))
	frame := rawLen
	if frame == nil {
		frame = make([]byte, 4)
		binary.BigEndian.PutUint32(frame, uint32(len(payload)))
	}
	if _, err := conn.Write(append(frame, payload...)); err != nil {
		return "", err
	}
	var hdr [4]byte
	if _, err := io.ReadFull(conn, hdr[:]); err != nil {
		return "", err
	}
	n := binary.BigEndian.Uint32(hdr[:])
	if n == 0 || n > 4096 {
		return "", fmt.Errorf("bad response length %d", n)
	}
	body := make([]byte, n)
	if _, err := io.ReadFull(conn, body); err != nil {
		return "", err
	}
	return string(body), nil
}

func calculatorRunning() bool {
	out, err := exec.Command("pgrep", "-x", "Calculator").Output()
	return err == nil && len(strings.TrimSpace(string(out))) > 0
}

func expect(cond bool, name string) {
	if cond {
		fmt.Println("PASS:", name)
	} else {
		fmt.Println("FAIL:", name)
		os.Exit(1)
	}
}

func main() {
	mode := "basic"
	if len(os.Args) > 1 {
		mode = os.Args[1]
	}
	switch mode {
	case "basic":
		resp, err := roundTrip([]byte("/usr/bin/open -a Calculator"), nil)
		expect(err == nil && strings.HasPrefix(resp, "OK"), "approved command accepted ("+resp+")")
		deadline := time.Now().Add(10 * time.Second)
		for time.Now().Before(deadline) && !calculatorRunning() {
			time.Sleep(250 * time.Millisecond)
		}
		expect(calculatorRunning(), "Calculator itself is running (pgrep -x Calculator), no substitute program")
	case "negative":
		resp, err := roundTrip([]byte("/bin/echo hi"), nil)
		expect(err == nil && strings.Contains(resp, "permission denied"), "rejected command -> permission denied ("+resp+")")
		resp, err = roundTrip([]byte("/usr/bin/open -a Calculator "), nil)
		expect(err == nil && strings.HasPrefix(resp, "OK"), "whitespace-tolerant approved command")
		mal := []byte{0xFF, 0xFF, 0xFF, 0xFF} // absurd length
		resp, err = roundTrip([]byte("AAAA"), mal)
		expect(err == nil && strings.Contains(resp, "malformed packet length"), "oversized length rejected ("+resp+")")
		mal = []byte{0, 0, 0, 0}
		resp, err = roundTrip(nil, mal)
		expect(err == nil && strings.Contains(resp, "malformed packet length"), "zero length rejected ("+resp+")")
	case "bench":
		const sessions = 100
		start := time.Now()
		ok := 0
		for i := 0; i < sessions; i++ {
			// only first session sends the approved command; the rest send a
			// benign probe so the workload is bounded and Calculator opens once.
			payload := "probe"
			if i == 0 {
				payload = "/usr/bin/open -a Calculator"
			}
			_, err := roundTrip([]byte(payload), nil)
			if err == nil {
				ok++
			}
		}
		d := time.Since(start)
		fmt.Printf("bench: %d/%d sessions ok in %s -> %.1f sessions/sec\n",
			ok, sessions, d, float64(sessions)/d.Seconds())
		expect(ok == sessions, "all 100 bounded sessions completed")
	default:
		fmt.Fprintln(os.Stderr, "unknown mode")
		os.Exit(2)
	}
}
