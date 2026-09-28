export { TextField } from './forms/text-field';

export function Button(props: { label: string }) {
  return <button>{props.label}</button>;
}

export function formatPrice(price: number): string {
  return `EUR ${price.toFixed(2)}`;
}
