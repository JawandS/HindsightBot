#!/usr/bin/env bash
set -euo pipefail

VERSION="v3.4.1"
BINARY_URL="https://github.com/tailwindlabs/tailwindcss/releases/download/${VERSION}/tailwindcss-linux-x64"
OUTPUT="./tailwindcss"

echo "Downloading Tailwind CSS ${VERSION} for linux/amd64..."
curl -fsSL "$BINARY_URL" -o "$OUTPUT"
chmod +x "$OUTPUT"
echo "Done: $OUTPUT"
