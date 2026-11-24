import type { AppNotification } from "@/api/notifications";

type CategoryMeta = { label: string; icon: string };
type LevelMeta = { label: string; icon: string };

export const NOTIFICATION_CATEGORIES: Record<AppNotification["category"], CategoryMeta> = {
  system: { label: "Sistema", icon: "pi pi-cog" },
  sales: { label: "Vendas", icon: "pi pi-shopping-cart" },
  cash: { label: "Caixa", icon: "pi pi-wallet" },
  stock: { label: "Estoque", icon: "pi pi-box" },
  fiscal: { label: "Fiscal", icon: "pi pi-file" },
  finance: { label: "Financeiro", icon: "pi pi-chart-line" },
};

export const NOTIFICATION_LEVELS: Record<AppNotification["level"], LevelMeta> = {
  info: { label: "Informação", icon: "pi pi-info-circle" },
  success: { label: "Sucesso", icon: "pi pi-check-circle" },
  warning: { label: "Atenção", icon: "pi pi-exclamation-triangle" },
  error: { label: "Erro", icon: "pi pi-times-circle" },
};

export function notificationRelative(value: string) {
  const elapsed = Math.max(0, Date.now() - new Date(value).getTime());
  const minutes = Math.floor(elapsed / 60_000);
  if (minutes < 1) return "agora";
  if (minutes < 60) return `há ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `há ${hours} h`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `há ${days} ${days === 1 ? "dia" : "dias"}`;
  return new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "short" }).format(new Date(value));
}
