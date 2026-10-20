package main

import (
	"strings"
	"testing"

	"github.com/Welkon/emb-support/skills/powersupply/go/internal/server"
)

func unit(family string, maxV float64) *server.Unit {
	return &server.Unit{ID: "test", Family: family, Limits: server.Limits{MaxVoltage: maxV, MaxCurrent: 5}}
}

func TestDP100LimitExplainsTheBuckTopology(t *testing.T) {
	v := 9.0
	err := checkUnitLimits(unit("dp100", 4.79), &v, nil)
	if err == nil {
		t.Fatal("expected an error")
	}
	msg := err.Error()
	for _, want := range []string{"4.79", "buck", "input voltage", "psu channels"} {
		if !strings.Contains(msg, want) {
			t.Fatalf("message %q does not mention %q", msg, want)
		}
	}
}

func TestOtherFamiliesKeepTheShortMessage(t *testing.T) {
	v := 31.0
	err := checkUnitLimits(unit("rigol", 30), &v, nil)
	if err == nil {
		t.Fatal("expected an error")
	}
	if strings.Contains(err.Error(), "buck") {
		t.Fatalf("unrelated family got the buck hint: %q", err.Error())
	}
}

func TestWithinLimitsPasses(t *testing.T) {
	v, i := 3.3, 0.1
	if err := checkUnitLimits(unit("dp100", 4.79), &v, &i); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
}
