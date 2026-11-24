from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("starrp", "0054_stock_advice")]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="cosmos_enabled",
            field=models.BooleanField(
                default=False,
                help_text="Exibe a assistente Cosmos para este usuário. Administradores da conta sempre têm acesso.",
            ),
        ),
        migrations.AddField(
            model_name="historicaluserprofile",
            name="cosmos_enabled",
            field=models.BooleanField(
                default=False,
                help_text="Exibe a assistente Cosmos para este usuário. Administradores da conta sempre têm acesso.",
            ),
        ),
        migrations.AddField(
            model_name="notification",
            name="permission",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="Permissão necessária para receber a notificação. Vazio usa a categoria.",
                max_length=120,
            ),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["recipient", "read_at", "created_at"], name="notif_rec_read_created_idx"),
        ),
    ]
