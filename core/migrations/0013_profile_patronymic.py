from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0012_remove_sickleave_file_url_sickleave_file_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='patronymic',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
    ]
