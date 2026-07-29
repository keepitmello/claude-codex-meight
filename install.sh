#!/bin/sh
# claude-codex-meight installer: creates a local venv and the `meight` CLI shim.
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="${MEIGHT_BIN_DIR:-$HOME/.local/bin}"
SDK_PIN="openai-codex==0.144.4"
INSTALL_LAUNCHD=0
LOAD_LAUNCHD=0

for arg in "$@"; do
  case "$arg" in
    --launchd) INSTALL_LAUNCHD=1 ;;
    --load-launchd) INSTALL_LAUNCHD=1; LOAD_LAUNCHD=1 ;;
    *)
      echo "error: unknown option: $arg" >&2
      echo "usage: ./install.sh [--launchd|--load-launchd]" >&2
      exit 1
      ;;
  esac
done

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
"$PY" -m venv --clear "$REPO_DIR/.venv"
VENV_PY="$REPO_DIR/.venv/bin/python"
"$VENV_PY" -m pip install --quiet --upgrade pip
"$VENV_PY" -m pip install --quiet "$SDK_PIN"
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

# 4. optional LaunchAgent
if [ "$INSTALL_LAUNCHD" -eq 1 ]; then
  if [ "$LOAD_LAUNCHD" -eq 1 ]; then
    "$REPO_DIR/.venv/bin/python" "$REPO_DIR/meight.py" launchd install --load
  else
    "$REPO_DIR/.venv/bin/python" "$REPO_DIR/meight.py" launchd install
  fi
fi

echo "note: worker state lives in \${MEIGHT_HOME:-~/.meight}/repos/<repo-key>/workers/<name>/"
echo "done. try: meight --help"
