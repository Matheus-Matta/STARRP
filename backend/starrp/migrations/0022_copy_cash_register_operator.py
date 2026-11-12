"""Caixa passa a ter UM operador e cada usuário UM caixa: o 1º operador de cada caixa vira o
operador, e quem estava em mais de um caixa fica no que ele tem turno em andamento (senão, o
primeiro por filial e nome)."""
from django.db import migrations


def copy(apps, schema_editor):
    CashRegister = apps.get_model("starrp", "CashRegister")
    CashSession = apps.get_model("starrp", "CashSession")
    taken = set()
    # 1º o caixa do turno em andamento de cada operador (o PDV dele está nesse caixa agora).
    for register_id, user_id in CashSession._base_manager.filter(
            deleted_at__isnull=True, status__in=["open", "pending_opening", "pending_approval"]).values_list(
            "register_id", "opened_by_id"):
        register = CashRegister._base_manager.filter(pk=register_id, operator__isnull=True).first()
        if register is not None and user_id not in taken and register.operators.filter(pk=user_id).exists():
            taken.add(user_id)
            CashRegister._base_manager.filter(pk=register_id).update(operator_id=user_id)
    for register in CashRegister._base_manager.filter(deleted_at__isnull=True, operator__isnull=True).order_by(
            "store_id", "name"):
        for user in register.operators.order_by("pk"):
            if user.pk not in taken:
                taken.add(user.pk)
                CashRegister._base_manager.filter(pk=register.pk).update(operator=user)
                break


class Migration(migrations.Migration):
    dependencies = [("starrp", "0021_cash_register_operator")]
    operations = [migrations.RunPython(copy, migrations.RunPython.noop)]
