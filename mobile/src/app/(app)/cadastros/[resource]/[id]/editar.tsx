import { findResource } from "@front/resources";
import { useLocalSearchParams } from "expo-router";

import { Guard } from "@/components/Guard";
import { ResourceForm } from "@/components/resource/ResourceForm";
import { EmptyState } from "@/components/ui";

/** Edição de um registro de qualquer cadastro da retaguarda. */
export default function EditRecordScreen() {
  const { resource: name, id } = useLocalSearchParams<{ resource: string; id: string }>();
  const resource = findResource(String(name));
  if (!resource) return <EmptyState icon="slash" title="Tela não encontrada" />;
  return (
    <Guard permission={`${resource.permission}.manage`} module={resource.module}>
      <ResourceForm resource={resource} id={String(id)} />
    </Guard>
  );
}
