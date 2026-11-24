import { http, type Page } from "./http";

export type AppNotification = {
  id: string;
  category: "system" | "sales" | "cash" | "stock" | "fiscal" | "finance";
  level: "info" | "success" | "warning" | "error";
  title: string;
  body: string;
  url: string;
  entity: string;
  object_id: string;
  read_at: string | null;
  created_at: string;
};

export const notificationsApi = {
  list: () => http.get<Page<AppNotification>>("/notifications/", { params: { page_size: 8 } }).then((r) => r.data),
  unreadCount: () => http.get<{ count: number }>("/notifications/unread-count/").then((r) => r.data.count),
  read: (id: string) => http.post<AppNotification>(`/notifications/${id}/read/`, {}).then((r) => r.data),
  readAll: () => http.post<{ count: number }>("/notifications/read-all/", {}).then((r) => r.data.count),
};
