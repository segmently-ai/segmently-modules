# The finished task: a new component in the catalog, its docs not updated yet.
cat > src/catalog/scanner.py <<'PY'
class BarcodeScanner:
    """Reads the ISBN-13 from a photo of a book's barcode and looks the book up."""

    def scan(self, image: bytes) -> str:
        raise NotImplementedError
PY
git add -- src/catalog/scanner.py
git commit -q -m "catalog: barcode scanner"
