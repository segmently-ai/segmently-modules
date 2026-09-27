# The catalog module doc grows past the split signal (600 lines): three large sections.
{
  printf '# Catalog\n\nLists and finds books.\n\n'
  printf '## EXISTING Components - DO NOT CREATE NEW\n\n'
  printf '| Name | Path | Purpose |\n|------|------|---------|\n'
  printf '| BookRepository | `src/catalog/service.py` | Loads books |\n'
  for title in Search Pricing Formats; do
    printf '\n## %s\n\n' "$title"
    for i in $(seq 1 240); do
      printf -- '- %s rule %d: keep this behaviour as documented.\n' "$title" "$i"
    done
  done
} > modules/catalog/MODULE.md
git add -- modules/catalog/MODULE.md
git commit -q -m "catalog: the doc grew"
