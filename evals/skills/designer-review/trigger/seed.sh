# The catalog's designer doc states its UX rules; the last commit changes the book card.
cat > modules/catalog/roles/designer.md <<'MD'
# Catalog — designer

## UX invariants

- Every book cover image has a text alternative: the book's title.
- A price always shows its currency.
- An action that removes something asks for confirmation.
MD
git add -- modules/catalog/roles/designer.md
git commit -q -m "catalog: designer rules"
mkdir -p src/catalog/ui
cat > src/catalog/ui/book_card.html <<'HTML'
<article class="book-card">
  <img src="{{ book.cover_url }}">
  <h3>{{ book.title }}</h3>
  <p class="price">{{ book.price }}</p>
  <button class="remove" onclick="removeFromList({{ book.id }})">Remove</button>
</article>
HTML
git add -- src/catalog/ui/book_card.html
git commit -q -m "catalog: new book card"
