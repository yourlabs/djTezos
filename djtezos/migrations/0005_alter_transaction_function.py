# Generated by Django 3.2 on 2021-05-13 16:33

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('djtezos', '0004_alter_transaction_amount'),
    ]

    operations = [
        migrations.AlterField(
            model_name='transaction',
            name='function',
            field=models.CharField(blank=True, db_index=True, max_length=100, null=True),
        ),
    ]
