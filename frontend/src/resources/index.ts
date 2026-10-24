/** Registro de todos os cadastros. Para criar um novo, declare-o e inclua aqui. */
import { fiscalProfiles, financialAccounts, warehouses } from "./backoffice";
import { brands, categories, products, serviceRules } from "./catalog";
import {
  cashSessions, financialCategories, installments, payables, receivables, transactions,
} from "./finance";
import { fiscalConfigs, inboundNfes, invoices } from "./fiscal";
import { customerGroups, customers, suppliers } from "./partners";
import { coupons, discountTables } from "./promotions";
import { sales } from "./sales";
import { cashRegisters, freightTables, metafieldDefinitions, paymentMethods, roles, stores, users } from "./settings";
import {
  labelTemplates, stockBalances, stockDocuments, stockLots, stockMovements, storageBins,
} from "./stock";
import type { ResourceDef } from "./types";

/** A ordem aqui é a ordem dentro de cada grupo do menu (o grupo vem do `group` de cada cadastro). */
export const resources: ResourceDef[] = [
  // Vendas
  sales, customers, customerGroups,
  // Catálogo
  products, categories, brands, serviceRules, metafieldDefinitions,
  // Promoções
  discountTables, coupons,
  // Compras
  suppliers, inboundNfes,
  // Estoque
  stockBalances, stockMovements, stockDocuments, stockLots, labelTemplates,
  // Logística
  freightTables, warehouses, storageBins,
  // Financeiro
  receivables, payables, installments, transactions, cashSessions, cashRegisters, paymentMethods, financialAccounts,
  financialCategories,
  // Fiscal
  invoices, fiscalConfigs, fiscalProfiles,
  // Configurações
  stores, users, roles,
];

const byName = new Map(resources.map((r) => [r.name, r]));

export function findResource(name: string) {
  return byName.get(name);
}
