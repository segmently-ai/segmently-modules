# A registered role doc went missing: next ranks a lint error first.
rm modules/catalog/roles/qa.md
git add -- modules/catalog/roles/qa.md
git commit -q -m "lose the catalog qa doc"
