/** Avaliações: moderação na retaguarda e o link público que o cliente recebe. */
import { http } from "./http";

const data = <T>(p: Promise<{ data: T }>) => p.then((r) => r.data);

export type ReviewLink = { url: string; text: string; phone: string };
export type PublicReview = {
  store: string; logo_url: string | null; sale: number; date: string; customer: string;
  delivery: { available: boolean; done: boolean };
  products: { id: string; name: string; image: string | null; done: boolean }[];
};

export const reviewsApi = {
  approve: (id: string) => data(http.post(`/reviews/${id}/approve/`, {})),
  reject: (id: string, reason: string) => data(http.post(`/reviews/${id}/reject/`, { reason })),
  link: (sale: string) => data(http.get<ReviewLink>("/reviews/link/", { params: { sale } })),
  publicView: (token: string) => data(http.get<PublicReview>(`/public/reviews/${token}/`)),
  /** O cliente envia as notas (JSON em `data`) e as fotos de cada produto (`photos_<id>`). */
  submit: (token: string, payload: unknown, photos: Record<string, File[]>) => {
    const form = new FormData();
    form.append("data", JSON.stringify(payload));
    for (const [product, files] of Object.entries(photos)) files.forEach((f) => form.append(`photos_${product}`, f));
    return data(http.post<{ created: number; view: PublicReview }>(`/public/reviews/${token}/`, form, { timeout: 120_000 }));
  },
};
