package webassets

import "embed"

// FS contains the production React build.
//
//go:embed dist
var FS embed.FS
