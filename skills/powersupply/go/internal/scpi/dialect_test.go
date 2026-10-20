package scpi

import "testing"

func TestDetectFamily(t *testing.T) {
	cases := map[string]string{
		"RIGOL TECHNOLOGIES,DP832,SN,1.0":      "rigol",
		"Keysight Technologies,E36312A,SN,1.0": "keysight",
		"Siglent Technologies,SPD3303X,SN,1.0": "siglent",
		"Rohde&Schwarz,HMC8043,SN,1.0":         "rns",
		"KORAD,KA3005P,SN,1.0":                 "korad",
		"GW INSTEK,GPP-3323,SN,1.0":            "gwinstek",
		"B&K PRECISION,9130B,SN,1.0":           "bkprecision",
		"ITECH,IT6302,SN,1.0":                  "itech",
		"OWON,SPE3103,SN,1.0":                  "owon",
		"AIM-TTI,PL303QMD,SN,1.0":              "aimtti",
		"ACME,PSU-1,SN,1.0":                    "generic",
	}
	for idn, want := range cases {
		if got := detectFamily(idn); got != want {
			t.Errorf("detectFamily(%q) = %q, want %q", idn, got, want)
		}
	}
}

func TestKoradCommands(t *testing.T) {
	d, err := byName("korad")
	if err != nil {
		t.Fatal(err)
	}
	if got := d.SetV(1, 5); got != "VSET1:5.00" {
		t.Errorf("set voltage = %q", got)
	}
	if got := d.SetI(1, 1); got != "ISET1:1.000" {
		t.Errorf("set current = %q", got)
	}
	if got := d.MeasureV(1); got != "VOUT1?" {
		t.Errorf("measure voltage = %q", got)
	}
	if got := d.Output(1, true); got != "OUT1" {
		t.Errorf("output = %q", got)
	}
}

func TestSiglentAndKeysight(t *testing.T) {
	s, _ := byName("siglent")
	if got := s.SetV(2, 12); got != ":CH2:VOLT 12" {
		t.Errorf("siglent set voltage = %q", got)
	}
	if got := s.Output(2, true); got != ":OUTP CH2,ON" {
		t.Errorf("siglent output = %q", got)
	}
	k, _ := byName("keysight")
	if got := k.Select(2); got != ":INSTrument:NSELect 2" {
		t.Errorf("keysight select = %q", got)
	}
}
