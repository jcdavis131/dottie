#!/usr/bin/env bash
# create_private_repo.sh — scaffolds private GitHub repo for personal-graphify
# Solo personal project, no connection to employer, built with public/free-tier only
set -e

REPO_NAME="${1:-personal-graphify}"
VISIBILITY="${2:-private}"  # private recommended

if ! command -v gh &> /dev/null; then
  echo "gh CLI not found. Install from https://cli.github.com/ then auth: gh auth login"
  echo "Alternatively, manually create repo on github.com/new and push:"
  echo "  cd $REPO_NAME && git init && git remote add origin git@github.com:YOURUSER/$REPO_NAME.git"
  exit 1
fi

if [ ! -d "$REPO_NAME" ]; then
  echo "Repo dir $REPO_NAME not found in current path. Run from parent of personal-graphify or pass path."
  # assume current dir is repo itself
  REPO_PATH="."
else
  REPO_PATH="$REPO_NAME"
fi

# If REPO_PATH is ., repo name is from folder
cd "$REPO_PATH"
if [ ! -d ".git" ]; then
  git init
  git add .
  git commit -m "feat: personal-graphify v0.1.0 — Ollama-first Graphify fork with Cursor skills (solo, free-tier only)"
fi

echo "Creating GitHub repo $REPO_NAME ($VISIBILITY)..."
gh repo create "$REPO_NAME" --"$VISIBILITY" --source=. --remote=origin --push -d "Personal Graphify — Knowledge Graphs for AI Coding Assistants (Ollama-first, for Davis family ecosystem). Solo personal project, no connection to employer."

echo "Done: https://github.com/$(gh api user --jq .login)/$REPO_NAME"
echo "Next: install skills: ./scripts/install_cursor_skills.sh ~/path/to/cursor-skills-repo"
