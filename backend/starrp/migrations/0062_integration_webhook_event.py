import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("starrp", "0061_integrations_by_kind")]

    operations = [
        migrations.CreateModel(
            name="IntegrationWebhookEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True)),
                ("provider", models.CharField(db_index=True, max_length=40)),
                ("provider_event_id", models.CharField(max_length=255)),
                ("event_type", models.CharField(db_index=True, max_length=120)),
                ("payload", models.JSONField(default=dict)),
                ("headers", models.JSONField(blank=True, default=dict)),
                ("status", models.CharField(choices=[("received", "Recebido"), ("processed", "Processado"), ("ignored", "Ignorado"), ("failed", "Falhou")], db_index=True, default="received", max_length=20)),
                ("processed_at", models.DateTimeField(blank=True, null=True)),
                ("error", models.TextField(blank=True)),
                ("account", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="starrp.account")),
                ("integration", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="webhook_events", to="starrp.integration")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="integrationwebhookevent",
            constraint=models.UniqueConstraint(fields=("integration", "provider_event_id"), name="uniq_integration_webhook_event"),
        ),
    ]
