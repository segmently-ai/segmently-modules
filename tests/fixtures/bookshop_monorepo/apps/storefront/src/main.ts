import { cartTotal } from '@bookshop/cart';
import { findBook } from '@bookshop/catalog';
import { Button } from '@bookshop/ui-kit';

export function renderBookPage(isbn: string) {
  const book = findBook(isbn);
  return { title: book?.title, buy: Button({ label: 'Buy' }), total: cartTotal([isbn]) };
}
