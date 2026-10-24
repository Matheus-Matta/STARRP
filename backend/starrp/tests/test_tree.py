"""Cadastro em árvore: só o topo (`?root=1`), os filhos (`?parent=`) e quantos filhos cada um tem."""


def test_categorias_em_arvore(ctx):
    api = ctx.client()
    url = "/api/v1/catalog/categories/"
    roupas = api.post(url, {"name": "Roupas"}, format="json").json()
    api.post(url, {"name": "Camisetas", "parent": roupas["id"]}, format="json")
    api.post(url, {"name": "Calças", "parent": roupas["id"]}, format="json")
    api.post(url, {"name": "Calçados"}, format="json")

    roots = api.get(f"{url}?root=1&ordering=name").json()["results"]
    children = api.get(f"{url}?parent={roupas['id']}&ordering=name").json()["results"]

    assert [(r["name"], r["children_count"]) for r in roots] == [("Calçados", 0), ("Roupas", 2)]
    assert [c["name"] for c in children] == ["Calças", "Camisetas"]
