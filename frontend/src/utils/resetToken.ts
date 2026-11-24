/** O token do link de redefinição de senha vem depois do `#` (`#token=...`): não chega ao servidor nem aos logs. */
export function resetTokenFrom(hash: string): string {
  return new URLSearchParams(hash.replace(/^#/, "")).get("token") ?? "";
}
