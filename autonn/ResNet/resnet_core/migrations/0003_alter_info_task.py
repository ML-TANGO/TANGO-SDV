# Generated by Django 3.2.12 on 2023-09-08 06:12

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('resnet_core', '0002_alter_info_task'),
    ]

    operations = [
        migrations.AlterField(
            model_name='info',
            name='task',
            field=models.CharField(blank=True, default='detection', max_length=50, null=True),
        ),
    ]