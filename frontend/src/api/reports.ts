import { cleanParams, http, type ListParams } from "./http";

export type Summary = {
  sales_count: number;
  revenue: string;
  average_ticket: string;
  discounts: string;
  returns_total: string;
  cancelled_count: number;
  gross_margin: string;
};

export type Dashboard = {
  summary: Summary;
  by_day: { day: string; count: number; revenue: string }[];
  by_payment_method: { method__name: string; total: string; count: number }[];
  top_products: { description: string; sold_quantity: string; revenue: string; margin: string }[];
  by_seller: { seller__first_name: string; seller__username: string; revenue: string; commission: string }[];
  open_sales: number;
};

export const reportsApi = {
  dashboard: (params: ListParams = {}) =>
    http.get<Dashboard>("/reports/dashboard/", { params: cleanParams(params) }).then((r) => r.data),
};
