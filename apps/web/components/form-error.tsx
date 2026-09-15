/** A one-line error message under a form, or nothing when there isn't one. */
export function FormError({ message }: { message: string | null }) {
  if (!message) return null;
  return <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{message}</p>;
}
