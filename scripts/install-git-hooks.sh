#!/usr/bin/env bash
# Install the project's git hooks by pointing core.hooksPath at the
# tracked .githooks/ directory.
#
# Idempotent: safe to run multiple times. The hook file is committed
# (in .githooks/), so this is a one-time setup per clone.
#
# Usage:
#   scripts/install-git-hooks.sh

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
HOOKS_DIR="$REPO_ROOT/.githooks"
HOOK_FILE="$HOOKS_DIR/pre-commit"

if [ ! -f "$HOOK_FILE" ]; then
    echo "ERROR: $HOOK_FILE not found."
    echo "Are you in a clone where the hook has been committed?"
    exit 1
fi

# Make the hook executable (no-op if already executable)
chmod +x "$HOOK_FILE"

# Point git at the tracked hooks dir
git config core.hooksPath "$HOOKS_DIR"

echo "✅ Installed git hooks:"
echo "   core.hooksPath = $HOOKS_DIR"
echo ""
echo "Hook: $HOOK_FILE"
echo "Test it: try to commit a file with a raw sqlite3.connect( call"
echo "         (should be rejected with a clear error message)."
