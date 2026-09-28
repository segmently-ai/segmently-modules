export interface Book {
  isbn: string;
  title: string;
  author: string;
  price: number;
}

const BOOKS: Book[] = [];

export function findBook(isbn: string): Book | undefined {
  return BOOKS.find((book) => book.isbn === isbn);
}

export function formatPrice(price: number): string {
  return `${price.toFixed(2)} EUR`;
}
