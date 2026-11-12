/**
 * Tarefas em segundo plano (Configurações): as rodando agora e as antigas, com o progresso e o botão de parar.
 * O registro nasce do botão que inicia o trabalho: aqui só se acompanha e para.
 */
import { defineAsyncComponent } from "vue";

import { tasksApi } from "@/api/tasks";

import { choices, defineResource } from "./types";

const TaskProgress = defineAsyncComponent(() => import("@/components/tasks/TaskProgress.vue"));

export const taskStatus = choices({ running: "Em andamento", completed: "Concluída", failed: "Falha", stopped: "Parada" });
const statusTones = { running: "info", completed: "success", failed: "danger", stopped: "neutral" } as const;
const taskKind = choices({ price_round: "Precificação: leitura do mercado", seo_round: "Analítico de SEO: análise dos produtos",
                           price_read: "Precificação: leitura de um produto", seo_read: "Analítico de SEO: análise de um produto" });
const running = (v: Record<string, unknown>) => v.status === "running";

export const backgroundTasks = defineResource({
  name: "tarefas",
  title: "Tarefas",
  singular: "tarefa",
  feminine: true,
  endpoint: "/background-tasks/",
  permission: "catalog",
  icon: "pi pi-sync",
  group: "Configurações",
  ordering: "-started_at",
  creatable: false,
  editable: false,
  deletable: false,
  readOnly: true,
  searchable: false,
  summary: TaskProgress,
  poll: { while: running, done: "Tarefa encerrada", message: "Em andamento: esta tela se atualiza sozinha. Você pode sair e voltar depois." },
  columns: [
    { key: "kind_display", label: "Tarefa", title: true, sortable: false },
    { key: "status", label: "Situação", type: "tag", map: taskStatus.map, tones: statusTones },
    { key: "done", label: "Feitos" },
    { key: "total", label: "Total" },
    { key: "percent", label: "%", sortable: false },
    { key: "started_by_name", label: "Quem iniciou", sortable: false, mobile: false },
    { key: "started_at", label: "Início", type: "datetime" },
    { key: "finished_at", label: "Fim", type: "datetime", mobile: false },
  ],
  filters: [
    { name: "status", label: "Situação", type: "select", options: taskStatus.options },
    { name: "kind", label: "Tarefa", type: "select", options: taskKind.options },
  ],
  fields: [],
  display: {
    badges: (v) => [{ label: taskStatus.map[String(v.status)] ?? "", tone: statusTones[v.status as keyof typeof statusTones] }],
    sections: [
      { title: "Detalhes", icon: "pi pi-info-circle", items: [
        { label: "Quem iniciou", key: "started_by_name" },
        { label: "Início", key: "started_at", type: "datetime" },
        { label: "Fim", key: "finished_at", type: "datetime" },
        { label: "Aviso", key: "error", span: "full", visible: (v) => Boolean(v.error), tone: () => "danger" },
      ] },
    ],
  },
  formActions: [
    { label: "Parar", icon: "pi pi-stop-circle", severity: "danger", permission: "catalog.manage", visible: (v) => v.can_stop === true,
      confirm: "Parar esta tarefa? O lote em andamento termina, e o que já foi feito fica salvo.", success: "Tarefa parada",
      run: ({ id }) => tasksApi.stop(id) },
  ],
});
