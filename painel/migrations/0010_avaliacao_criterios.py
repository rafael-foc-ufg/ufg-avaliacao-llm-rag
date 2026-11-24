from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('painel', '0009_avaliacao_processos'),
    ]

    operations = [
        migrations.RemoveField(model_name='avaliacao', name='veredito'),
        migrations.RemoveField(model_name='avaliacao', name='aprovada'),
        migrations.AddField(
            model_name='avaliacao',
            name='vereditos',
            field=models.JSONField(default=list, verbose_name='vereditos do juiz'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='avaliacao',
            name='mediana',
            field=models.PositiveSmallIntegerField(default=0, verbose_name='avaliação mediana'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='avaliacao',
            name='fidelidade',
            field=models.FloatField(null=True, verbose_name='fidelidade'),
        ),
        migrations.AddField(
            model_name='avaliacao',
            name='precisao',
            field=models.FloatField(default=0, verbose_name='precisão'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='avaliacao',
            name='completude',
            field=models.FloatField(default=0, verbose_name='completude'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='avaliacao',
            name='amplitude',
            field=models.FloatField(default=0, verbose_name='amplitude da nota'),
            preserve_default=False,
        ),
    ]
