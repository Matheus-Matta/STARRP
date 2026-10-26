/** Um balão de dica por gráfico: o valor em destaque e a série em segundo plano. */
import { reactive } from "vue";

export type TipRow = { label: string; value: string; color?: string };
export function useTooltip() {
  const tip = reactive({ show: false, x: 0, y: 0, title: "", rows: [] as TipRow[] });
  function show(event: MouseEvent | FocusEvent, title: string, rows: TipRow[]) {
    const target = event.currentTarget as Element | null;
    const rect = target?.getBoundingClientRect();
    const point = "clientX" in event && event.clientX ? { x: event.clientX, y: event.clientY }
      : { x: (rect?.left ?? 0) + (rect?.width ?? 0) / 2, y: rect?.top ?? 0 };
    Object.assign(tip, { show: true, x: point.x, y: point.y, title, rows });
  }
  const hide = () => (tip.show = false);
  return { tip, show, hide };
}
