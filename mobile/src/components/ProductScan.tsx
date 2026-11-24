/** Lê um código pela câmera e abre a ficha do produto (ou avisa que não achou). */
import { useRouter } from "expo-router";
import { useState } from "react";

import { lookupCode } from "@/api/stock";
import { Scanner } from "@/components/Scanner";
import { notify } from "@/lib/dialog";
import { errorMessage } from "@/lib/useApi";

export function useProductScan() {
  const router = useRouter();
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);

  async function openCode(code: string) {
    setBusy(true);
    try {
      const variant = await lookupCode(code);
      if (variant) router.push({ pathname: "/produto/[id]", params: { id: variant.id } });
      else notify("Produto não encontrado", `Nenhum produto com o código ${code}.`);
    } catch (e) {
      notify("Erro na consulta", errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const scanner = <Scanner visible={visible} onClose={() => setVisible(false)} onCode={(c) => void openCode(c)}
                           title="Leia o código do produto" />;
  return { scanner, open: () => setVisible(true), busy, openCode };
}
