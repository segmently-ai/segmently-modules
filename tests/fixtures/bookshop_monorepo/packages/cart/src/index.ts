import { findBook } from '@bookshop/catalog';
import { lineTotal } from './lines';

export function cartTotal(isbns: string[]): number {
  const prices = isbns.map((isbn) => findBook(isbn)?.price ?? 0);
  return prices.map((price) => lineTotal(price, 1)).reduce((a, b) => a + b, 0);
}
