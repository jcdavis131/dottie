#!/usr/bin/env bash
# install_cursor_skills.sh — copy personal-graphify skills into cursor skills repo
# Solo personal project, no connection to employer, built with public/free-tier only
set -e

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST_DIR="${1:-$HOME/cursor-skills}"  # or ~/path/to/cursor-skills-repo

echo "Source: $SRC_DIR"
echo "Dest: $DEST_DIR"
mkdir -p "$DEST_DIR/skills" "$DEST_DIR/.cursor/rules" "$DEST_DIR/.agents/skills"

# copy 3 skills
for skill in graphify-core graphify-personal graphify-agentic; do
  echo "→ Installing skill $skill"
  rm -rf "$DEST_DIR/skills/$skill"
  cp -r "$SRC_DIR/skills/$skill" "$DEST_DIR/skills/"
done

# copy cursor rule
cp "$SRC_DIR/.cursor/rules/graphify.mdc" "$DEST_DIR/.cursor/rules/graphify.mdc"
echo "→ Wrote $DEST_DIR/.cursor/rules/graphify.mdc (alwaysApply: true)"

# copy agents skill
mkdir -p "$DEST_DIR/.agents/skills/graphify"
cp "$SRC_DIR/.agents/skills/graphify/SKILL.md" "$DEST_DIR/.agents/skills/graphify/SKILL.md"
echo "→ Wrote $DEST_DIR/.agents/skills/graphify/SKILL.md"

# also install into current project if called from project root
if [ -f "./pyproject.toml" ] || [ -d "./.git" ]; then
  echo "→ Also installing into current project .cursor/rules"
  mkdir -p .cursor/rules .agents/skills/graphify
  cp "$SRC_DIR/.cursor/rules/graphify.mdc" .cursor/rules/graphify.mdc
  cp "$SRC_DIR/.agents/skills/graphify/SKILL.md" .agents/skills/graphify/SKILL.md
  echo "Wrote .cursor/rules/graphify.mdc and .agents/skills/graphify/SKILL.md in $(pwd)"
fi

echo ""
echo "Done. Next:"
echo "  cd $DEST_DIR && git add skills/graphify-* .cursor/rules/graphify.mdc .agents/skills/graphify && git commit -m 'feat: personal-graphify skills (71.5x token reduction, Ollama-first)'"
echo "  In any repo: pgraphify . && cat graphify-out/GRAPH_REPORT.md"
echo ""
echo "Solo personal project, no connection to employer, built with public/free-tier only"
