import { findResource } from "@front/resources";
import { useLocalSearchParams } from "expo-router";

import { Guard } from "@/components/Guard";
import { ResourceForm } from "@/components/resource/ResourceForm";
import { EmptyState } from "@/components/ui";

/** Cadastro novo de qualquer cadastro da retaguarda (aceita valores pela URL: `?kind=exit`). */
export default function NewRecordScreen() {
  const { resource: name, ...query } = useLocalSearchParams<Record<string, string>>();
  const resource = findResource(String(name));
  if (!resource) return <EmptyState icon="slash" title="Tela não encontrada" />;
  return (
    <Guard permission={`${resource.permission}.manage`} module={resource.module} needsStore>
      <ResourceForm resource={resource} id={null} query={query} />
    </Guard>
  );
}
