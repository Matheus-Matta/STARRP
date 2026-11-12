/** Registro de todos os cadastros. Para criar um novo, declare-o e inclua aqui. */
import { fiscalProfiles, financialAccounts, warehouses } from "./backoffice";
import { brands, categories, products, serviceRules } from "./catalog";
import {
  cashSessions, financialCategories, installments, payables, receivables, transactions,
} from "./finance";
import { fiscalConfigs, inboundNfes, invoices } from "./fiscal";
import { customerGroups, customers, suppliers } from "./partners";
import { competitorPrices, priceChecks } from "./pricing";
import { coupons, discountTables } from "./promotions";
import { reviews } from "./reviews";
import { seoChecks } from "./seo";
import { stockAdvices } from "./stockAdvice";
import { logisticsRules, stockRules, storeRules } from "./rules";
import { sales } from "./sales";
import {
  cashRegisters, freightTables, metafieldDefinitions, paymentMethods, roles, stores, users,
} from "./settings";
import {
  labelTemplates, receivingDivergences, stockBalances, stockDocuments, stockLots, stockMovements, storageBins,
} from "./stock";
import { backgroundTasks } from "./tasks";
import type { ResourceDef } from "./types";

/** A ordem aqui é a ordem dentro de cada grupo do menu (o grupo vem do `group` de cada cadastro). */
export const resources: ResourceDef[] = [
  // Vendas
  sales, priceChecks, competitorPrices, seoChecks, reviews, customers, customerGroups,
  // Catálogo
  products, categories, brands, serviceRules, metafieldDefinitions,
  // Promoções
  discountTables, coupons,
  // Compras
  suppliers, inboundNfes,
  // Estoque
  stockBalances, stockMovements, stockDocuments, stockLots, stockAdvices, labelTemplates, stockRules,
  // Logística
  freightTables, warehouses, storageBins, receivingDivergences, logisticsRules,
  // Financeiro
  receivables, payables, installments, transactions, cashSessions, cashRegisters, paymentMethods, financialAccounts,
  financialCategories,
  // Fiscal
  invoices, fiscalConfigs, fiscalProfiles,
  // Configurações
  stores, storeRules, users, roles, backgroundTasks,
];

const byName = new Map(resources.map((r) => [r.name, r]));

export function findResource(name: string) {
  return byName.get(name);
}
