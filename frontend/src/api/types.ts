/**
 * Tipos de domínio, todos derivados do OpenAPI do backend (`schema.d.ts`).
 * Regerar com `npm run api:types` sempre que o backend mudar um serializer:
 * o que quebrar na compilação é exatamente o que precisa de ajuste.
 */
import type { components } from "./schema";

type S = components["schemas"];

export type Product = S["Product"];
/** Variante: o item que se vende (PDV) e se estoca. `current_price` já vem com a promoção vigente. */
export type Variant = S["VariantList"] & { current_price?: string };
export type VariantLookup = Variant & {
  list_price: string; promotion: string | null; scale_quantity: string | null; volume: number | null;
};
export type Sale = S["Sale"];
export type SaleItem = S["SaleItem"];
export type Payment = S["Payment"];
export type PaymentMethod = S["PaymentMethod"];
export type CashSession = S["CashSession"];
export type CashRegister = S["CashRegister"];
export type CashMovement = S["CashMovement"];
export type Customer = S["Customer"];
export type Store = S["Store"];

export type Me = {
  id: number;
  username: string;
  name: string;
  email: string;
  is_superuser: boolean;
  /** `logo_url`: logo da empresa (1080×1080); vazio = as impressões usam o do Starrp. */
  account: { id: string; name: string; modules: string[]; logo_url: string | null } | null;
  role: { code: string; name: string; rank: number } | null;
  /** Cargo principal + os somados (as permissões já vêm somadas em `permissions`). */
  roles: { code: string; name: string }[];
  all_stores: boolean;
  stores: { id: string; name: string }[];
  active_store_id: string | null;
  /** Loja principal do usuário (o PDV entra nela quando está em "todas as lojas"). */
  default_store_id: string | null;
  is_seller: boolean;
  permissions: string[];
};

export type Seller = { user_id: number; name: string; code: string };

/** Vitrine do produto no PDV (GET /pdv/products/{id}/). */
export type PdvProductView = {
  id: string;
  name: string;
  type: string;
  unit: string;
  sale_method: string;
  reference: string;
  category_name: string | null;
  brand_name: string | null;
  /** HTML já limpo no backend (nh3). */
  description: string;
  images: string[];
  axes: { id: string; name: string; values: { id: string; value: string }[] }[];
  variants: {
    id: string; sku: string; name: string; is_default: boolean; price: string; current_price: string;
    /** null = não controla estoque (serviço, kit). */
    stock: string | null;
    barcode: string;
    /** eixo → valor escolhido. */
    options: Record<string, string>;
    images: string[];
  }[];
  services: { variant: string; name: string; sku: string; price: string; description: string }[];
  /** Ficha técnica personalizada (Configurações → Campos personalizados). */
  specs: { key: string; label: string; value: unknown; text: string }[];
};

export type PdvBootstrap = {
  /** Vê o que há na gaveta (quem aprova fechamento); o operador fecha às cegas. */
  sees_drawer: boolean;
  server_time: string;
  store: Store;
  terminal: S["Terminal"];
  payment_methods: PaymentMethod[];
  cash_registers: CashRegister[];
  cash_session: CashSession | null;
  sellers: Seller[];
  /** "seller": monta e guarda pedidos; "cashier": cobra, abre/fecha o turno (tem `cash.manage`). */
  mode: "seller" | "cashier";
  /** Minutos sem mexer até a tela do caixa bloquear sozinha. */
  lock_minutes: number;
  has_cash_action_password: boolean;
};

/** Autorização de um superior enviada junto da ação (ver `useApproval`). */
export type Approval = { username: string; password: string } | { cash_password: string };
