package config

import (
	"os"
	"path/filepath"
	"testing"
)

// The Python CLI resolves its state dir the same way; both must agree or they
// read two different config files.
func TestPSUHomeWins(t *testing.T) {
	t.Setenv("PSU_HOME", filepath.Join(t.TempDir(), "explicit"))
	t.Setenv("PSU_CONFIG", "")
	if got, want := Path(), filepath.Join(os.Getenv("PSU_HOME"), "config.json"); got != want {
		t.Fatalf("Path() = %q, want %q", got, want)
	}
}

func TestPSUConfigWins(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("PSU_CONFIG", filepath.Join(dir, "custom.json"))
	if got, want := Path(), filepath.Join(dir, "custom.json"); got != want {
		t.Fatalf("Path() = %q, want %q", got, want)
	}
}

func TestProjectHomeIsPreferred(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("PSU_HOME", "")
	t.Setenv("PSU_CONFIG", "")

	project := t.TempDir()
	local := filepath.Join(project, ".emb-agent", "bench", "psu")
	if err := os.MkdirAll(local, 0o755); err != nil {
		t.Fatal(err)
	}
	t.Chdir(project)

	if got := Home(); got != local {
		t.Fatalf("Home() = %q, want %q", got, local)
	}
}

func TestNewProjectStaysInside(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("PSU_HOME", "")
	t.Setenv("PSU_CONFIG", "")

	project := t.TempDir()
	if err := os.MkdirAll(filepath.Join(project, ".emb-agent"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Chdir(project)

	want := filepath.Join(project, ".emb-agent", "bench", "psu")
	if got := Home(); got != want {
		t.Fatalf("Home() = %q, want %q", got, want)
	}
}

func TestLegacyDirIsKept(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("PSU_HOME", "")
	t.Setenv("PSU_CONFIG", "")
	legacy := filepath.Join(home, ".local", "share", "psu")
	if err := os.MkdirAll(legacy, 0o755); err != nil {
		t.Fatal(err)
	}

	project := t.TempDir()
	if err := os.MkdirAll(filepath.Join(project, ".emb-agent"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Chdir(project)

	if got := Home(); got != legacy {
		t.Fatalf("Home() = %q, want %q", got, legacy)
	}
}

func TestOutsideProjectFallsBackToLegacy(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("PSU_HOME", "")
	t.Setenv("PSU_CONFIG", "")
	t.Chdir(t.TempDir())

	if got, want := Home(), filepath.Join(home, ".local", "share", "psu"); got != want {
		t.Fatalf("Home() = %q, want %q", got, want)
	}
}
