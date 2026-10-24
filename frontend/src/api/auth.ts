import type { Me } from "./types";
import { http } from "./http";

export const authApi = {
  login: (username: string, password: string) => http.post("/auth/login/", { username, password }),
  logout: () => http.post("/auth/logout/", {}),
  me: (storeId?: string | null) =>
    http.get<Me>("/me/", { headers: storeId ? { "X-Store-ID": storeId } : {} }).then((r) => r.data),
  requestReset: (email: string) => http.post("/auth/password-reset/", { email }),
};
