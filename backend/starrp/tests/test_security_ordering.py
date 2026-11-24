"""Ordenação não revela custo nem segredo (docs/SEGURANCA.md S-17)."""


def test_caixa_nao_ordena_por_custo_e_gerente_ordena(ctx):
    ctx.product(name="Caneca", price="30.00")
    cashier = ctx.client(ctx.user("caixa", "cashier"))
    manager = ctx.client(ctx.user("gerente", "manager"))

    for ordering in ("average_cost", "-last_cost"):
        assert cashier.get("/api/v1/catalog/variants/", {"ordering": ordering}).status_code == 400
    assert manager.get("/api/v1/catalog/variants/", {"ordering": "average_cost"}).status_code == 200


def test_ninguem_ordena_por_segredo(ctx):
    api = ctx.client()
    for ordering in ("user__password", "csc_token", "certificate_password"):
        response = api.get("/api/v1/users/", {"ordering": ordering})
        assert response.status_code == 400, (ordering, response.status_code)
