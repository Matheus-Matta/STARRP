from django.contrib import admin
from django.contrib.auth.models import AnonymousUser
from django.test import Client

from starrp.models import Account, FiscalConfig, Product


def _section_names(model):
    model_admin = admin.site._registry[model]
    request = type("Request", (), {"user": AnonymousUser()})()
    return [name for name, _options in model_admin.get_fieldsets(request)]


def test_generic_admin_groups_large_forms_semantically():
    product_sections = _section_names(Product)
    fiscal_sections = _section_names(FiscalConfig)
    account_sections = _section_names(Account)

    assert "Dados principais" in product_sections
    assert "Escopo e vínculos" in product_sections
    assert "Dados fiscais" in product_sections
    assert "Endereço" in fiscal_sections
    assert "Dados fiscais" in fiscal_sections
    assert "Cosmos e automações" in account_sections
    assert "Pesquisa de preços" in account_sections
    assert "SEO" in account_sections


def test_admin_change_form_renders_section_navigation(ctx):
    ctx.admin.is_staff = True
    ctx.admin.is_superuser = True
    ctx.admin.save(update_fields=["is_staff", "is_superuser"])
    client = Client()
    client.force_login(ctx.admin)

    response = client.get("/admin/starrp/product/add/", HTTP_HOST="localhost")

    assert response.status_code == 200
    html = response.content.decode()
    assert 'class="form-section-nav"' in html
    assert "Dados principais" in html
    assert "Escopo e vínculos" in html
    assert "Dados fiscais" in html
    assert "admin-autocomplete" in html
    assert "vForeignKeyRawIdAdminField" not in html


def test_role_permissions_are_translated_grouped_checkboxes(ctx):
    ctx.admin.is_staff = True
    ctx.admin.is_superuser = True
    ctx.admin.save(update_fields=["is_staff", "is_superuser"])
    client = Client()
    client.force_login(ctx.admin)

    response = client.get("/admin/starrp/role/add/", HTTP_HOST="localhost")

    assert response.status_code == 200
    html = response.content.decode()
    assert 'class="permission-checklist"' in html
    assert 'type="checkbox"' in html and 'name="permissions"' in html
    assert "Produtos e catálogo" in html
    assert "Produtos e catálogo: executar ações" in html
    assert '<select name="permissions"' not in html
