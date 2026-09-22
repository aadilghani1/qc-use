#!/bin/sh
# Install qc-use with uv, then register its skill for your coding agents.
#   curl -LsSf https://raw.githubusercontent.com/aadilghani1/qc-use/main/install.sh | sh
# QC_USE_SOURCE installs another source, such as a version (qc-use==0.3.0), a wheel, or a git URL.
set -eu

source="${QC_USE_SOURCE:-qc-use}"

if ! command -v uv >/dev/null 2>&1; then
  echo "qc-use: uv is missing. Installing uv from https://astral.sh/uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  PATH="${UV_INSTALL_DIR:-${XDG_BIN_HOME:-$HOME/.local/bin}}:$PATH"
fi

uv tool install --python 3.12 --upgrade "$source"
bin="$(uv tool dir --bin)"
"$bin/qc-use" skill install
"$bin/qc-use" --version

case ":$PATH:" in
  *":$bin:"*) ;;
  *) echo "qc-use: $bin is not on your PATH. Run: uv tool update-shell" ;;
esac

cat <<'EOF'

Next:
  1. Get a Vercel AI Gateway key: https://vercel.com/docs/ai-gateway
  2. Try the demo:  AI_GATEWAY_API_KEY=your-key qc-use demo --watch
  3. Restart your coding agent and ask: "Test our signup critical path on localhost:3000."
EOF
