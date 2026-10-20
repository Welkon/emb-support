package scpi

import (
	"fmt"
	"strconv"
	"strings"
)

func fnum(v float64) string { return strconv.FormatFloat(v, 'g', 6, 64) }

type Dialect struct {
	Name       string
	Channels   []int
	Select     func(int) string
	SetV       func(int, float64) string
	SetI       func(int, float64) string
	GetV       func(int) string
	GetI       func(int) string
	MeasureV   func(int) string
	MeasureI   func(int) string
	MeasureP   func(int) string
	Output     func(int, bool) string
	OutputRead func(int) string
	OVP        func(int, float64) string
	OCP        func(int, float64) string
}

func genericDialect() *Dialect {
	return &Dialect{
		Name: "generic", Channels: []int{1},
		SetV: func(_ int, v float64) string { return ":VOLTage " + fnum(v) },
		SetI: func(_ int, a float64) string { return ":CURRent " + fnum(a) },
		GetV: func(int) string { return ":VOLTage?" }, GetI: func(int) string { return ":CURRent?" },
		MeasureV:   func(int) string { return ":MEASure:VOLTage?" },
		MeasureI:   func(int) string { return ":MEASure:CURRent?" },
		MeasureP:   func(int) string { return ":MEASure:POWEr?" },
		Output:     func(_ int, on bool) string { return ":OUTPut " + onOff(on) },
		OutputRead: func(int) string { return ":OUTPut?" },
		OVP: func(_ int, v float64) string {
			return ":VOLTage:PROTection " + fnum(v) + ";:VOLTage:PROTection:STATe ON"
		},
	}
}

func onOff(on bool) string {
	if on {
		return "ON"
	}
	return "OFF"
}

func normalizeDialect(d *Dialect) *Dialect {
	if d != nil && d.OVP == nil && d.Name != "korad" {
		d.OVP = genericDialect().OVP
	}
	return d
}

func byName(name string) (*Dialect, error) {
	name = strings.ToLower(strings.TrimSpace(name))
	switch name {
	case "", "auto":
		return nil, nil
	case "generic":
		return genericDialect(), nil
	case "rigol":
		return &Dialect{
			Name: "rigol", Channels: []int{1, 2, 3},
			SetV:       func(n int, v float64) string { return fmt.Sprintf(":CHANnel%d:VOLTage %s", n, fnum(v)) },
			SetI:       func(n int, a float64) string { return fmt.Sprintf(":CHANnel%d:CURRent %s", n, fnum(a)) },
			GetV:       func(n int) string { return fmt.Sprintf(":CHANnel%d:VOLTage?", n) },
			GetI:       func(n int) string { return fmt.Sprintf(":CHANnel%d:CURRent?", n) },
			MeasureV:   func(n int) string { return fmt.Sprintf(":MEASure:VOLTage? CHANnel%d", n) },
			MeasureI:   func(n int) string { return fmt.Sprintf(":MEASure:CURRent? CHANnel%d", n) },
			MeasureP:   func(n int) string { return fmt.Sprintf(":MEASure:POWEr? CHANnel%d", n) },
			Output:     func(n int, on bool) string { return fmt.Sprintf(":OUTPut CHANnel%d,%s", n, onOff(on)) },
			OutputRead: func(n int) string { return fmt.Sprintf(":OUTPut? CHANnel%d", n) },
			OVP:        func(n int, v float64) string { return fmt.Sprintf(":CHANnel%d:OVP %s", n, fnum(v)) },
			OCP:        func(n int, a float64) string { return fmt.Sprintf(":CHANnel%d:OCP %s", n, fnum(a)) },
		}, nil
	case "keysight":
		return &Dialect{
			Name: "keysight", Channels: []int{1, 2, 3}, Select: func(n int) string { return fmt.Sprintf(":INSTrument:NSELect %d", n) },
			SetV: func(_ int, v float64) string { return ":VOLTage " + fnum(v) },
			SetI: func(_ int, a float64) string { return ":CURRent " + fnum(a) },
			GetV: func(int) string { return ":VOLTage?" }, GetI: func(int) string { return ":CURRent?" },
			MeasureV:   func(int) string { return ":MEASure:VOLTage?" },
			MeasureI:   func(int) string { return ":MEASure:CURRent?" },
			Output:     func(_ int, on bool) string { return ":OUTPut " + onOff(on) },
			OutputRead: func(int) string { return ":OUTPut?" },
			OVP:        func(_ int, v float64) string { return ":OUTPut:OVP:VOLTage " + fnum(v) },
		}, nil
	case "siglent":
		return &Dialect{
			Name: "siglent", Channels: []int{1, 2},
			SetV:       func(n int, v float64) string { return fmt.Sprintf(":CH%d:VOLT %s", n, fnum(v)) },
			SetI:       func(n int, a float64) string { return fmt.Sprintf(":CH%d:CURR %s", n, fnum(a)) },
			GetV:       func(n int) string { return fmt.Sprintf(":CH%d:VOLT?", n) },
			GetI:       func(n int) string { return fmt.Sprintf(":CH%d:CURR?", n) },
			MeasureV:   func(n int) string { return fmt.Sprintf(":MEAS:VOLT? CH%d", n) },
			MeasureI:   func(n int) string { return fmt.Sprintf(":MEAS:CURR? CH%d", n) },
			MeasureP:   func(n int) string { return fmt.Sprintf(":MEAS:POW? CH%d", n) },
			Output:     func(n int, on bool) string { return fmt.Sprintf(":OUTP CH%d,%s", n, onOff(on)) },
			OutputRead: func(n int) string { return fmt.Sprintf(":OUTP? CH%d", n) },
		}, nil
	case "rns":
		return &Dialect{
			Name: "rns", Channels: []int{1, 2, 3, 4}, Select: func(n int) string { return fmt.Sprintf(":INSTrument:NSELect %d", n) },
			SetV: func(_ int, v float64) string { return ":VOLTage " + fnum(v) },
			SetI: func(_ int, a float64) string { return ":CURRent " + fnum(a) },
			GetV: func(int) string { return ":VOLTage?" }, GetI: func(int) string { return ":CURRent?" },
			MeasureV:   func(int) string { return ":MEASure:VOLTage?" },
			MeasureI:   func(int) string { return ":MEASure:CURRent?" },
			MeasureP:   func(int) string { return ":MEASure:POWEr?" },
			Output:     func(n int, on bool) string { return fmt.Sprintf(":OUTPut:CHANnel%d:STATe %s", n, onOff(on)) },
			OutputRead: func(n int) string { return fmt.Sprintf(":OUTPut:CHANnel%d:STATe?", n) },
		}, nil
	case "korad":
		return &Dialect{
			Name: "korad", Channels: []int{1, 2},
			SetV:     func(n int, v float64) string { return fmt.Sprintf("VSET%d:%.2f", n, v) },
			SetI:     func(n int, a float64) string { return fmt.Sprintf("ISET%d:%.3f", n, a) },
			GetV:     func(n int) string { return fmt.Sprintf("VSET%d?", n) },
			GetI:     func(n int) string { return fmt.Sprintf("ISET%d?", n) },
			MeasureV: func(n int) string { return fmt.Sprintf("VOUT%d?", n) },
			MeasureI: func(n int) string { return fmt.Sprintf("IOUT%d?", n) },
			Output: func(n int, on bool) string {
				if on {
					return fmt.Sprintf("OUT%d", n)
				}
				return "OUT0"
			},
		}, nil
	case "gwinstek":
		return &Dialect{Name: "gwinstek", Channels: []int{1, 2}, Select: func(n int) string { return fmt.Sprintf(":INSTrument:NSELect %d", n) },
			SetV: func(_ int, v float64) string { return ":VOLTage " + fnum(v) }, SetI: func(_ int, a float64) string { return ":CURRent " + fnum(a) },
			GetV: func(int) string { return ":VOLTage?" }, GetI: func(int) string { return ":CURRent?" },
			MeasureV: func(int) string { return ":MEASure:VOLTage?" }, MeasureI: func(int) string { return ":MEASure:CURRent?" },
			MeasureP: func(int) string { return ":MEASure:POWEr?" }, Output: func(_ int, on bool) string { return ":OUTPut " + onOff(on) }, OutputRead: func(int) string { return ":OUTPut?" }}, nil
	case "bkprecision":
		return &Dialect{Name: "bkprecision", Channels: []int{1, 2, 3}, Select: func(n int) string { return fmt.Sprintf(":INSTrument:NSELect %d", n) },
			SetV: func(_ int, v float64) string { return ":VOLTage " + fnum(v) }, SetI: func(_ int, a float64) string { return ":CURRent " + fnum(a) },
			GetV: func(int) string { return ":VOLTage?" }, GetI: func(int) string { return ":CURRent?" },
			MeasureV: func(int) string { return ":MEASure:VOLTage?" }, MeasureI: func(int) string { return ":MEASure:CURRent?" },
			MeasureP: func(int) string { return ":MEASure:POWEr?" }, Output: func(_ int, on bool) string { return ":OUTPut " + onOff(on) }, OutputRead: func(int) string { return ":OUTPut?" }}, nil
	case "owon":
		return &Dialect{Name: "owon", Channels: []int{1, 2},
			SetV: func(n int, v float64) string { return fmt.Sprintf(":CH%d:VOLT %s", n, fnum(v)) },
			SetI: func(n int, a float64) string { return fmt.Sprintf(":CH%d:CURR %s", n, fnum(a)) },
			GetV: func(n int) string { return fmt.Sprintf(":CH%d:VOLT?", n) }, GetI: func(n int) string { return fmt.Sprintf(":CH%d:CURR?", n) },
			MeasureV: func(n int) string { return fmt.Sprintf(":MEAS:VOLT? CH%d", n) }, MeasureI: func(n int) string { return fmt.Sprintf(":MEAS:CURR? CH%d", n) },
			Output: func(n int, on bool) string { return fmt.Sprintf(":OUTP CH%d,%s", n, onOff(on)) }, OutputRead: func(n int) string { return fmt.Sprintf(":OUTP? CH%d", n) }}, nil
	case "itech":
		return &Dialect{Name: "itech", Channels: []int{1, 2, 3}, Select: func(n int) string { return fmt.Sprintf(":INSTrument:NSELect %d", n) },
			SetV: func(_ int, v float64) string { return ":VOLTage " + fnum(v) }, SetI: func(_ int, a float64) string { return ":CURRent " + fnum(a) },
			GetV: func(int) string { return ":VOLTage?" }, GetI: func(int) string { return ":CURRent?" },
			MeasureV: func(int) string { return ":MEASure:VOLTage?" }, MeasureI: func(int) string { return ":MEASure:CURRent?" }, MeasureP: func(int) string { return ":MEASure:POWer?" },
			Output: func(_ int, on bool) string { return ":OUTPut " + onOff(on) }, OutputRead: func(int) string { return ":OUTPut?" },
			OVP: func(_ int, v float64) string {
				return ":VOLTage:PROTection " + fnum(v) + ";:VOLTage:PROTection:STATe ON"
			}}, nil
	case "aimtti":
		d := genericDialect()
		d.Name, d.Channels = "aimtti", []int{1, 2}
		return d, nil
	default:
		return nil, fmt.Errorf("unknown SCPI family %q", name)
	}
}

func detectFamily(idn string) string {
	u := strings.ToUpper(idn)
	switch {
	case strings.Contains(u, "RIGOL"):
		return "rigol"
	case strings.Contains(u, "KEYSIGHT"), strings.Contains(u, "AGILENT"), strings.Contains(u, "HEWLETT"):
		return "keysight"
	case strings.Contains(u, "SIGLENT"):
		return "siglent"
	case strings.Contains(u, "ROHDE"), strings.Contains(u, "R&S"), strings.Contains(u, "HAMEG"):
		return "rns"
	case strings.Contains(u, "KORAD"), strings.Contains(u, "TENMA"):
		return "korad"
	case strings.Contains(u, "GW INSTEK"), strings.Contains(u, "GWINSTEK"):
		return "gwinstek"
	case strings.Contains(u, "B&K"), strings.Contains(u, "BK PRECISION"):
		return "bkprecision"
	case strings.Contains(u, "ITECH"):
		return "itech"
	case strings.Contains(u, "OWON"):
		return "owon"
	case strings.Contains(u, "AIM"), strings.Contains(u, "TTI"):
		return "aimtti"
	default:
		return "generic"
	}
}

// Families returns all supported SCPI family names.
func Families() []string {
	return []string{"rigol", "keysight", "siglent", "rns", "korad", "gwinstek", "bkprecision", "owon", "itech", "aimtti", "generic"}
}
