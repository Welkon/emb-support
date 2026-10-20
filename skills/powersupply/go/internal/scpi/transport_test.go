package scpi

import (
	"bufio"
	"net"
	"strconv"
	"strings"
	"testing"
	"time"
)

func TestTCPTransport(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()
	go func() {
		conn, err := ln.Accept()
		if err != nil {
			return
		}
		defer conn.Close()
		r := bufio.NewReader(conn)
		for {
			line, err := r.ReadString('\n')
			if err != nil {
				return
			}
			switch strings.TrimSpace(line) {
			case "*IDN?":
				_, _ = conn.Write([]byte("ACME,PSU-1,SN,1.0\n"))
			case ":VOLTage?":
				_, _ = conn.Write([]byte("12.5\n"))
			}
		}
	}()
	port := ln.Addr().(*net.TCPAddr).Port
	inst, err := Dial("TCPIP::127.0.0.1::"+strconv.Itoa(port)+"::SOCKET", time.Second, 9600)
	if err != nil {
		t.Fatal(err)
	}
	defer inst.Close()
	idn, err := inst.Query("*IDN?")
	if err != nil || idn != "ACME,PSU-1,SN,1.0" {
		t.Fatalf("idn = %q, %v", idn, err)
	}
	v, err := inst.Query(":VOLTage?")
	if err != nil || v != "12.5" {
		t.Fatalf("voltage = %q, %v", v, err)
	}
}
