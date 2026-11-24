/**
 * Botões extras do registro (`ResourceDef.formActions`): confirmar, cancelar, baixar, fechar caixa...
 * Igual a `FormActions.vue`: botões pequenos (sem `severity` = secundário com contorno) e, no celular, numa
 * linha própria que rola para o lado. Somem sem permissão/módulo ou quando `visible` diz que não cabe;
 * pedem confirmação quando declarado. Os que abrem um diálogo próprio da retaguarda (ou imprimem) avisam
 * que são feitos no computador.
 */
import * as Haptics from "expo-haptics";
import { useState } from "react";
import { ScrollView } from "react-native";

import { Button, type IconName } from "@/components/ui";
import { confirmAction, notify } from "@/lib/dialog";
import { errorMessage } from "@/lib/useApi";
import { iconOf, useAccess } from "@/shared/frontend";
import { isWebOnly } from "@/shared/resource";
import type { FormAction, FormActionContext } from "@/shared/types";

const VARIANT = { secondary: "outlined-secondary", danger: "danger", success: "success", contrast: "contrast" } as const;

export function FormActions({ actions, ctx }: { actions: FormAction[]; ctx: FormActionContext }) {
  const { can, hasModule } = useAccess();
  const [running, setRunning] = useState<string | null>(null);

  const shown = actions.filter((a) => (!a.permission || can(a.permission)) && hasModule(a.module)
    && (!a.visible || a.visible(ctx.values)));
  if (!shown.length) return null;
  const webOnly = (a: FormAction) => !a.run || isWebOnly(a.dialog);

  async function execute(action: FormAction) {
    setRunning(action.label);
    try {
      await action.run!(ctx);
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      if (action.success) notify(action.success);
      await ctx.reload();
    } catch (e) {
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      notify(`Não foi possível: ${action.label.toLowerCase()}`, errorMessage(e));
    } finally {
      setRunning(null);
    }
  }

  function start(action: FormAction) {
    if (webOnly(action)) {
      return notify(action.label, "Esta ação abre uma tela própria da retaguarda. Faça pelo computador.");
    }
    if (!action.confirm) return void execute(action);
    confirmAction(action.label, action.confirm, action.label, () => void execute(action), action.severity === "danger");
  }

  return (
    // `.head__actions` (≤640px): linha própria, rola para o lado, encosta nas bordas da página.
    <ScrollView horizontal showsHorizontalScrollIndicator={false} className="mx-[-16px] grow-0"
                contentContainerClassName="gap-[6.4px] px-4 pb-0.5">
      {shown.map((a) => (
        <Button key={a.label} label={a.label} compact icon={iconOf(a.icon, webOnly(a) ? "monitor" : "check") as IconName}
                variant={VARIANT[a.severity ?? "secondary"]}
                loading={running === a.label} disabled={!!running} onPress={() => start(a)} />
      ))}
    </ScrollView>
  );
}
