/** Do endereço da API ao cadastro na tela: "/catalog/products/" + id → "/cadastros/produtos/<id>". */
import { resources } from "@/resources";

const normalize = (endpoint: string) => `/${endpoint.replace(/^\/+|\/+$/g, "")}/`;

export function recordLink(endpoint: string | null | undefined, id?: string | null) {
  if (!endpoint) return null;
  const resource = resources.find((r) => r.endpoint === normalize(endpoint));
  if (!resource) return null;
  return id ? `/cadastros/${resource.name}/${id}` : `/cadastros/${resource.name}`;
}

/** Nome humano do cadastro ("produto"), para o botão "Abrir produto". */
export function recordLabel(endpoint: string | null | undefined) {
  const resource = endpoint ? resources.find((r) => r.endpoint === normalize(endpoint)) : undefined;
  return resource?.singular ?? "registro";
}
