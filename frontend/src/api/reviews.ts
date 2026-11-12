/** Avaliações: moderação na retaguarda e o link público que o cliente recebe. */
import { http } from "./http";

const data = <T>(p: Promise<{ data: T }>) => p.then((r) => r.data);

/** Um por tipo que a venda pode avaliar. `state`: none (sem link), active, used (já avaliado), expired. */
export type ReviewLinkKind = "order" | "delivery";
export type ReviewLink = {
  kind: ReviewLinkKind; label: string; state: "none" | "active" | "used" | "expired"; reviewed: boolean;
  url?: string; text?: string; phone?: string; expires_at?: string; used_at?: string | null; created_at?: string;
};
export type PublicReview = {
  kind: ReviewLinkKind; expires_at: string;
  store: string; logo_url: string | null; sale: number; date: string; customer: string;
  delivery: { available: boolean; done: boolean };
  products: { id: string; name: string; image: string | null; done: boolean }[];
};

export const reviewsApi = {
  approve: (id: string) => data(http.post(`/reviews/${id}/approve/`, {})),
  reject: (id: string, reason: string) => data(http.post(`/reviews/${id}/reject/`, { reason })),
  links: (sale: string) => data(http.get<ReviewLink[]>("/reviews/links/", { params: { sale } })),
  /** Gera o link do tipo (o que ainda vale volta igual); já avaliado = 409 `review_exists`. */
  generateLink: (sale: string, kind: ReviewLinkKind, days: number) =>
    data(http.post<ReviewLink[]>("/reviews/links/", { sale, kind, days })),
  publicView: (token: string) => data(http.get<PublicReview>(`/public/reviews/${token}/`)),
  /** O cliente envia as notas (JSON em `data`) e as fotos de cada produto (`photos_<id>`). */
  submit: (token: string, payload: unknown, photos: Record<string, File[]>) => {
    const form = new FormData();
    form.append("data", JSON.stringify(payload));
    for (const [product, files] of Object.entries(photos)) files.forEach((f) => form.append(`photos_${product}`, f));
    return data(http.post<{ created: number; kind: ReviewLinkKind }>(`/public/reviews/${token}/`, form, { timeout: 120_000 }));
  },
};
