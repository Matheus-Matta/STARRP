"""Gravar as tags de um registro a partir dos nomes digitados.

Ex.: set_tags(produto, ["Lançamento", "lançamento ", "Verão"], "product") deixa o
produto com DUAS tags; a que não existia na conta é criada na hora.
"""
from starrp.models import Tag


def set_tags(obj, names, scope, user=None):
    wanted = {}
    for name in names:
        clean = " ".join(str(name).split())[:40]
        if clean:
            wanted.setdefault(clean.casefold(), clean)
    existing = {t.normalized: t for t in Tag.all_objects.filter(
        account_id=obj.account_id, scope=scope, normalized__in=list(wanted), deleted_at__isnull=True)}
    tags = [existing.get(key) or Tag.all_objects.create(account_id=obj.account_id, scope=scope, name=name,
                                                       created_by=user)
            for key, name in wanted.items()]
    obj.tags.set(tags)
    return tags
