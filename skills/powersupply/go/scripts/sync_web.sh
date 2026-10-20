#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
rm -rf internal/webassets/dist
cp -R ../webapp/dist internal/webassets/dist
