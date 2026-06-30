import django.core.validators
import django.db.models.deletion
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0007_alter_room_confidence'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='projectspec',
            name='reinforcement_type',
        ),
        migrations.RemoveField(
            model_name='projectspec',
            name='column_size',
        ),
        migrations.RemoveField(
            model_name='projectspec',
            name='beam_size',
        ),
        migrations.AddField(
            model_name='projectspec',
            name='reinforcement_grade',
            field=models.CharField(
                choices=[('hyd', 'High Yield Deformed Bar (HYD)'), ('ms', 'Mild Steel Round Bar (MS)')],
                default='hyd',
                help_text='Project-wide default steel grade. Individual reinforcement rows can override this.',
                max_length=10,
            ),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='reinforcementspec',
            name='bar_role',
            field=models.CharField(
                choices=[('main', 'Main'), ('distribution', 'Distribution'), ('stirrup', 'Stirrup/Link')],
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='reinforcementspec',
            name='grade',
            field=models.CharField(
                blank=True,
                choices=[('hyd', 'High Yield Deformed Bar (HYD)'), ('ms', 'Mild Steel Round Bar (MS)')],
                help_text='Overrides the project-wide default grade for this row only. Leave blank to use the project default.',
                max_length=10,
                default='',
            ),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='reinforcementspec',
            name='spacing_mm',
            field=models.DecimalField(
                decimal_places=1,
                max_digits=6,
                help_text='Stirrup/link spacing when Bar Role is Stirrup; main-bar spacing when Bar Role is Main or Distribution.',
                validators=[
                    django.core.validators.MinValueValidator(Decimal('50')),
                    django.core.validators.MaxValueValidator(Decimal('400')),
                ],
            ),
        ),
        migrations.AddField(
            model_name='reinforcementspec',
            name='structural_member',
            field=models.ForeignKey(
                blank=True,
                null=True,
                help_text='Which labeled member (e.g. C1, B1) this row applies to. Required for Column/Beam rows; leave blank for Foundation/Slab.',
                on_delete=django.db.models.deletion.CASCADE,
                related_name='reinforcement_specs',
                to='projects.structuralmember',
            ),
        ),
    ]
