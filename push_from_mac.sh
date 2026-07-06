#!/bin/bash
# ============================================================
# Run this script on YOUR Mac (where your SSH key is)
# to push ta7tZero to GitHub.
#
# Prerequisites:
#   1. Your SSH key is added to GitHub: https://github.com/settings/keys
#      cat ~/yes.pub  →  paste the content there
#   2. The GitHub repo exists: https://github.com/amanem-saga/ta7tZero
#      (create it as EMPTY — no README, no .gitignore, no license)
# ============================================================

set -e

REPO_DIR="$HOME/ta7tZero"
BUNDLE="$REPO_DIR/ta7tZero.bundle"

# --- Step 1: Download the bundle ---
echo ">>> Downloading bundle..."
mkdir -p "$REPO_DIR"
cd "$REPO_DIR"
curl -L -o ta7tZero.bundle "BUNDLE_URL_PLACEHOLDER"

# --- Step 2: Clone from bundle ---
echo ">>> Cloning from bundle..."
git clone ta7tZero.bundle . --origin bundle
rm ta7tZero.bundle

# --- Step 3: Set up SSH remote ---
echo ">>> Setting up GitHub remote..."
git remote remove bundle
git remote add origin git@github.com:amanem-saga/ta7tZero.git

# --- Step 4: Add your SSH key to agent ---
echo ">>> Loading SSH key..."
eval "$(ssh-agent -s)"
ssh-add ~/yes 2>/dev/null || ssh-add ~/.ssh/id_ed25519 2>/dev/null || true

# --- Step 5: Push ---
echo ">>> Pushing to GitHub..."
git push -u origin main

echo ""
echo "✅ Done! Repo is at https://github.com/amanem-saga/ta7tZero"