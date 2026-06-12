#!/bin/sh
# claude-codex-meight installer: creates a local venv and the `meight` CLI shim.
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="${MEIGHT_BIN_DIR:-$HOME/.local/bin}"
SDK_PIN="openai-codex==0.1.0b3"

# 1. prerequisites
command -v codex >/dev/null 2>&1 || {
  echo "error: codex CLI not found. Install & authenticate it first:"
  echo "       https://developers.openai.com/codex"
  exit 1
}
PY="$(command -v python3 || true)"
[ -n "$PY" ] || { echo "error: python3 not found (>= 3.10 required)"; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || {
  echo "error: python3 >= 3.10 required (found $("$PY" -V))"; exit 1; }

# 2. venv + pinned SDK
echo "→ creating venv at $REPO_DIR/.venv"
"$PY" -m venv "$REPO_DIR/.venv"
"$REPO_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$REPO_DIR/.venv/bin/pip" install --quiet "$SDK_PIN"
echo "→ installed $SDK_PIN"

# 3. CLI shim
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/meight" <<SHIM
#!/bin/sh
exec "$REPO_DIR/.venv/bin/python" "$REPO_DIR/meight.py" "\$@"
SHIM
chmod +x "$BIN_DIR/meight"
echo "→ installed $BIN_DIR/meight"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "note: $BIN_DIR is not in your PATH — add it to use \`meight\` directly." ;;
esac

# 4. recommend global gitignore for per-repo state dirs
if ! git config --global core.excludesfile >/dev/null 2>&1 || \
   ! grep -qs "^\.meight/$" "$(git config --global core.excludesfile 2>/dev/null)" 2>/dev/null; then
  echo "note: worker state lives in <repo>/.meight/ — add it to your global gitignore:"
  echo "      echo '.meight/' >> \"\$(git config --global core.excludesfile || echo ~/.config/git/ignore)\""
fi

echo "done. try: meight --help"
