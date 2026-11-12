/** Tarefas em segundo plano (Configurações › Tarefas). */
import { http } from "./http";

export const tasksApi = {
  /** Para a rodada: o lote em andamento termina, e o próximo não começa. */
  stop: (id: string) => http.post(`/background-tasks/${id}/stop/`, {}).then((r) => r.data),
};
