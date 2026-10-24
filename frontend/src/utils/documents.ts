/** CPF e CNPJ: só dígitos, com conferência do dígito verificador. */
export const onlyDigits = (value: string) => value.replace(/\D/g, "");

function cpfOk(cpf: string) {
  if (cpf.length !== 11 || /^(\d)\1+$/.test(cpf)) return false;
  for (const size of [9, 10]) {
    let sum = 0;
    for (let i = 0; i < size; i++) sum += Number(cpf[i]) * (size + 1 - i);
    const digit = ((sum * 10) % 11) % 10;
    if (digit !== Number(cpf[size])) return false;
  }
  return true;
}

function cnpjOk(cnpj: string) {
  if (cnpj.length !== 14 || /^(\d)\1+$/.test(cnpj)) return false;
  const weights = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2];
  for (const size of [12, 13]) {
    let sum = 0;
    for (let i = 0; i < size; i++) sum += Number(cnpj[i]) * weights[i + (13 - size)]!;
    const rest = sum % 11;
    if ((rest < 2 ? 0 : 11 - rest) !== Number(cnpj[size])) return false;
  }
  return true;
}

export function documentError(value: string): string | null {
  const digits = onlyDigits(value);
  if (!digits) return null;
  if (digits.length === 11) return cpfOk(digits) ? null : "CPF inválido.";
  if (digits.length === 14) return cnpjOk(digits) ? null : "CNPJ inválido.";
  return "CPF tem 11 dígitos e CNPJ tem 14.";
}

export function formatDocument(value: string) {
  const d = onlyDigits(value);
  if (d.length === 11) return d.replace(/(\d{3})(\d{3})(\d{3})(\d{2})/, "$1.$2.$3-$4");
  if (d.length === 14) return d.replace(/(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})/, "$1.$2.$3/$4-$5");
  return value;
}
