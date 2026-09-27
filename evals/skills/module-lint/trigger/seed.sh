# Two registry mistakes lint reports: an unknown status (MS003) and an empty keyword (MS022).
python3 - <<'PY'
import json
path = "modules/registry.json"
with open(path, encoding="utf-8") as fh:
    data = json.load(fh)
data["modules"]["checkout"]["status"] = "archived"
data["modules"]["catalog"]["keywords"].append("")
with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
PY
git add -- modules/registry.json
git commit -q -m "registry edits"
