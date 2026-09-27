// payload.go - benign localhost command receiver (authorized lab fixture).
// Listens ONLY on 127.0.0.1. Accepts exactly one whitelisted command:
// /usr/bin/open -a Calculator . Everything else is rejected.
// Framing: 4-byte big-endian length prefix (<=64), then the command bytes.
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

const (
	listenAddr   = "127.0.0.1:18321"
	approvedCmd  = "/usr/bin/open -a Calculator"
	maxFrame     = 64
	readDeadline = 3 * time.Second
)

func main() {
	ln, err := net.Listen("tcp", listenAddr) // loopback-only by construction
	if err != nil {
		fmt.Fprintln(os.Stderr, "listen error:", err)
		os.Exit(2)
	}
	defer ln.Close()
	fmt.Println("listening on", ln.Addr().String())
	for {
		conn, err := ln.Accept()
		if err != nil {
			return // listener closed => normal shutdown path
		}
		go handle(conn)
	}
}

func handle(conn net.Conn) {
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(readDeadline))

	var hdr [4]byte
	if _, err := io.ReadFull(conn, hdr[:]); err != nil {
		respond(conn, "ERR malformed packet length: header unreadable")
		return
	}
	n := binary.BigEndian.Uint32(hdr[:])
	if n == 0 || n > maxFrame {
		respond(conn, fmt.Sprintf("ERR malformed packet length: %d", n))
		return
	}
	buf := make([]byte, n)
	if _, err := io.ReadFull(conn, buf); err != nil {
		respond(conn, "ERR malformed packet length: short body")
		return
	}
	cmd := strings.TrimSpace(string(buf))
	if cmd != approvedCmd {
		respond(conn, "ERR permission denied: command not approved")
		return
	}
	if err := exec.Command("/usr/bin/open", "-a", "Calculator").Start(); err != nil {
		respond(conn, "ERR exec: "+err.Error())
		return
	}
	respond(conn, "OK launched")
}

func respond(conn net.Conn, msg string) {
	b := []byte(msg)
	var hdr [4]byte
	binary.BigEndian.PutUint32(hdr[:], uint32(len(b)))
	_, _ = conn.Write(append(hdr[:], b...))
}
