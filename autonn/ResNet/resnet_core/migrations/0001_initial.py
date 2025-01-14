# Generated by Django 3.2.12 on 2023-09-08 01:17

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Info',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('userid', models.CharField(blank=True, default='', max_length=50, null=True)),
                ('project_id', models.CharField(blank=True, default='', max_length=50, null=True)),
                ('target_yaml', models.FileField(default='', upload_to='temp_files/')),
                ('data_yaml', models.FileField(default='', upload_to='temp_files/')),
                ('task', models.CharField(blank=True, default='classification', max_length=50, null=True)),
                ('status', models.CharField(blank=True, default='ready', max_length=10, null=True)),
                ('process_id', models.CharField(blank=True, max_length=50, null=True)),
            ],
        ),
    ]
