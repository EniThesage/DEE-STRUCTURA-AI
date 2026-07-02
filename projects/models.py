from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Project(models.Model):
    CITY_CHOICES = [
        ('lagos', 'Lagos'),
        ('ibadan', 'Ibadan'),
        ('abuja', 'Abuja'),
        ('port_harcourt', 'Port Harcourt'),
    ]

    BUILDING_TYPE_CHOICES = [
        ('residential', 'Residential'),
        ('commercial', 'Commercial'),
        ('institutional', 'Institutional'),
        ('industrial', 'Industrial'),
        ('mixed_use', 'Mixed Use'),
    ]

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='projects')
    name = models.CharField(max_length=200)
    client_name = models.CharField(max_length=200)
    location = models.CharField(max_length=20, choices=CITY_CHOICES)
    building_type = models.CharField(max_length=30, choices=BUILDING_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    footprint_width_m = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal('1')), MaxValueValidator(Decimal('200'))],
        help_text='Overall building footprint width, in metres — pre-filled from floor plan extraction, '
                   'editable on the Review Rooms page. Drives perimeter-based quantities (trenches, walls) '
                   'instead of an estimate. Leave blank to fall back to an estimated footprint.',
    )
    footprint_length_m = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal('1')), MaxValueValidator(Decimal('200'))],
        help_text='Overall building footprint length, in metres — see footprint_width_m.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class ProjectDrawing(models.Model):
    """A single uploaded drawing/document, tagged by discipline. Replaces
    FloorPlanUpload — the extraction pipeline now runs one discipline-specific
    pass per drawing rather than assuming one architectural floor plan
    contains everything a BOQ needs."""
    DISCIPLINE_CHOICES = [
        ('architectural', 'Architectural'),
        ('structural', 'Structural'),
        ('electrical', 'Electrical'),
        ('plumbing_mechanical', 'Plumbing/Mechanical'),
        ('specification_document', 'Specification Document'),
        ('other', 'Other'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='drawings')
    file = models.FileField(upload_to='drawings/%Y/%m/')
    discipline = models.CharField(max_length=30, choices=DISCIPLINE_CHOICES, default='architectural')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    extraction_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    extraction_error = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    extraction_flags = models.JSONField(
        default=dict, blank=True,
        help_text='Extraction-time notices for the review page: excluded_candidates '
                   '(items deliberately not turned into rooms), external_works_noted, area_mismatch_pct.',
    )
    reviewed = models.BooleanField(
        default=False,
        help_text='Engineer has reviewed/confirmed this drawing\'s extracted data. '
                   'BOQ generation is blocked until every architectural drawing is reviewed.',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f'{self.project.name} - {self.file.name}'


class Room(models.Model):
    CONFIDENCE_CHOICES = [
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
        ('manual', 'Manual'),
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='rooms')
    source_drawing = models.ForeignKey(
        ProjectDrawing, on_delete=models.SET_NULL, null=True, blank=True, related_name='rooms',
    )
    name = models.CharField(max_length=100)
    width = models.DecimalField(max_digits=8, decimal_places=2)
    length = models.DecimalField(max_digits=8, decimal_places=2)
    area = models.DecimalField(max_digits=10, decimal_places=2, editable=False)
    door_count = models.PositiveIntegerField(default=0, help_text='Door openings visible/confirmed for this room.')
    window_count = models.PositiveIntegerField(default=0, help_text='Window openings visible/confirmed for this room.')
    confidence = models.CharField(max_length=10, choices=CONFIDENCE_CHOICES, default='medium')
    is_manual = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        self.area = (self.width or 0) * (self.length or 0)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class StructuralElement(models.Model):
    ELEMENT_TYPE_CHOICES = [
        ('column', 'Column'),
        ('beam', 'Beam'),
        ('slab', 'Slab'),
        ('footing', 'Footing'),
        ('foundation_detail', 'Foundation Detail'),
    ]
    CONFIDENCE_CHOICES = Room.CONFIDENCE_CHOICES

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='structural_elements')
    source_drawing = models.ForeignKey(
        ProjectDrawing, on_delete=models.SET_NULL, null=True, blank=True, related_name='structural_elements',
    )
    element_type = models.CharField(max_length=20, choices=ELEMENT_TYPE_CHOICES)
    label = models.CharField(max_length=20, blank=True, help_text='As printed in the drawing schedule, e.g. C1, B2.')
    size = models.CharField(max_length=30, blank=True, help_text='e.g. 225x225')
    count = models.PositiveIntegerField(default=1)
    reinforcement_main = models.CharField(max_length=50, blank=True, help_text='e.g. 4Y16')
    reinforcement_links = models.CharField(max_length=50, blank=True, help_text='e.g. Y8@200')
    concrete_grade = models.CharField(max_length=10, blank=True)
    depth_mm = models.DecimalField(max_digits=7, decimal_places=1, null=True, blank=True)
    confidence = models.CharField(max_length=10, choices=CONFIDENCE_CHOICES, default='medium')
    is_manual = models.BooleanField(default=False)

    def __str__(self):
        return f'{self.label or self.get_element_type_display()} ({self.size})'


class ElectricalPoint(models.Model):
    POINT_TYPE_CHOICES = [
        ('lighting_point', 'Lighting Point'),
        ('socket_13a', '13A Socket'),
        ('socket_15a', '15A Socket'),
        ('switch', 'Switch'),
        ('distribution_board', 'Distribution Board'),
        ('cooker_point', 'Cooker Point'),
        ('ac_point', 'AC Point'),
        ('other', 'Other'),
    ]
    CONFIDENCE_CHOICES = Room.CONFIDENCE_CHOICES

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='electrical_points')
    source_drawing = models.ForeignKey(
        ProjectDrawing, on_delete=models.SET_NULL, null=True, blank=True, related_name='electrical_points',
    )
    point_type = models.CharField(max_length=30, choices=POINT_TYPE_CHOICES)
    description = models.CharField(max_length=200, blank=True)
    count = models.PositiveIntegerField(default=1)
    confidence = models.CharField(max_length=10, choices=CONFIDENCE_CHOICES, default='medium')
    is_manual = models.BooleanField(default=False)

    def __str__(self):
        return f'{self.get_point_type_display()} x{self.count}'


class PlumbingFixture(models.Model):
    FIXTURE_TYPE_CHOICES = [
        ('wc', 'WC'),
        ('wash_hand_basin', 'Wash Hand Basin'),
        ('sink', 'Sink'),
        ('shower', 'Shower'),
        ('bath', 'Bath'),
        ('floor_drain', 'Floor Drain'),
        ('water_heater', 'Water Heater'),
        ('other', 'Other'),
    ]
    CONFIDENCE_CHOICES = Room.CONFIDENCE_CHOICES

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='plumbing_fixtures')
    source_drawing = models.ForeignKey(
        ProjectDrawing, on_delete=models.SET_NULL, null=True, blank=True, related_name='plumbing_fixtures',
    )
    fixture_type = models.CharField(max_length=30, choices=FIXTURE_TYPE_CHOICES)
    description = models.CharField(max_length=200, blank=True)
    count = models.PositiveIntegerField(default=1)
    confidence = models.CharField(max_length=10, choices=CONFIDENCE_CHOICES, default='medium')
    is_manual = models.BooleanField(default=False)

    def __str__(self):
        return f'{self.get_fixture_type_display()} x{self.count}'


class SpecificationItem(models.Model):
    CATEGORY_CHOICES = [
        ('concrete', 'Concrete'),
        ('blockwork', 'Blockwork'),
        ('finishes', 'Finishes'),
        ('roofing', 'Roofing'),
        ('doors_windows', 'Doors/Windows'),
        ('services', 'Services'),
        ('general', 'General'),
    ]
    CONFIDENCE_CHOICES = Room.CONFIDENCE_CHOICES

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='specification_items')
    source_drawing = models.ForeignKey(
        ProjectDrawing, on_delete=models.SET_NULL, null=True, blank=True, related_name='specification_items',
    )
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    key = models.CharField(max_length=100, help_text='e.g. floor_finish')
    value = models.CharField(max_length=255, help_text='e.g. 600x600 vitrified tiles')
    confidence = models.CharField(max_length=10, choices=CONFIDENCE_CHOICES, default='medium')
    is_manual = models.BooleanField(default=False)

    def __str__(self):
        return f'{self.key}: {self.value}'


ADDITIONAL_SERVICES_CHOICES = [
    ('solar', 'Solar Power System'),
    ('cctv', 'CCTV Security'),
    ('fire_protection', 'Fire Protection System'),
    ('generator', 'Generator Backup'),
    ('borehole_treatment', 'Borehole Water Treatment'),
    ('intercom', 'Intercom System'),
]

REINFORCEMENT_GRADE_CHOICES = [
    ('hyd', 'High Yield Deformed Bar (HYD)'),
    ('ms', 'Mild Steel Round Bar (MS)'),
]


class ProjectSpec(models.Model):
    FOUNDATION_CHOICES = [
        ('strip', 'Strip Foundation'),
        ('pad', 'Pad Foundation'),
        ('raft', 'Raft Foundation'),
        ('pile', 'Pile Foundation'),
    ]
    CONCRETE_GRADE_CHOICES = [
        ('c15', 'C15'),
        ('c20', 'C20'),
        ('c25', 'C25'),
        ('c30', 'C30'),
        ('c35', 'C35'),
    ]
    FRAME_TYPE_CHOICES = [
        ('framed', 'Framed (Column & Beam)'),
        ('load_bearing', 'Load-Bearing Blockwork'),
    ]
    WALL_TYPE_CHOICES = [
        ('sandcrete_225', '225mm Sandcrete Block'),
        ('sandcrete_150', '150mm Sandcrete Block'),
        ('brick', 'Brick'),
        ('drywall', 'Drywall Partition'),
    ]
    ROOF_TYPE_CHOICES = [
        ('long_span_aluminum', 'Long Span Aluminium'),
        ('aluminum_step_tile', 'Aluminium Step Tile'),
        ('asbestos', 'Asbestos'),
        ('stone_coated_tile', 'Stone-Coated Tile'),
    ]
    TRUSS_TYPE_CHOICES = [
        ('timber', 'Timber Truss'),
        ('steel', 'Steel Truss'),
    ]
    FLOOR_FINISH_CHOICES = [
        ('terrazzo', 'Terrazzo'),
        ('tiles', 'Ceramic/Porcelain Tiles'),
        ('screed', 'Cement Screed'),
        ('wood', 'Wood/Laminate'),
    ]
    WALL_FINISH_CHOICES = [
        ('paint', 'Paint'),
        ('texture', 'Textured Coating'),
        ('wallpaper', 'Wallpaper'),
    ]
    CEILING_TYPE_CHOICES = [
        ('pop', 'POP (Plaster of Paris)'),
        ('plywood', 'Plywood'),
        ('gypsum', 'Gypsum Board'),
    ]
    ELECTRICAL_PACKAGE_CHOICES = [
        ('standard', 'Standard'),
        ('premium', 'Premium (Solar-Ready)'),
    ]
    WATER_SUPPLY_CHOICES = [
        ('borehole', 'Borehole'),
        ('mains', 'Mains/Public Supply'),
        ('both', 'Borehole + Mains'),
    ]

    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name='spec')

    foundation_type = models.CharField(max_length=20, choices=FOUNDATION_CHOICES)
    excavation_depth = models.DecimalField(
        max_digits=5, decimal_places=2, help_text='metres',
        validators=[MinValueValidator(Decimal('0.3')), MaxValueValidator(Decimal('5'))],
    )
    concrete_grade = models.CharField(max_length=10, choices=CONCRETE_GRADE_CHOICES)
    reinforcement_grade = models.CharField(
        max_length=10, choices=REINFORCEMENT_GRADE_CHOICES,
        help_text='Project-wide default steel grade. Individual reinforcement rows can override this.',
    )

    frame_type = models.CharField(max_length=20, choices=FRAME_TYPE_CHOICES)
    slab_thickness = models.DecimalField(
        max_digits=5, decimal_places=1, help_text='mm',
        validators=[MinValueValidator(Decimal('75')), MaxValueValidator(Decimal('500'))],
    )

    wall_type_external = models.CharField(max_length=20, choices=WALL_TYPE_CHOICES)
    wall_type_internal = models.CharField(max_length=20, choices=WALL_TYPE_CHOICES)
    wall_height = models.DecimalField(
        max_digits=5, decimal_places=2, help_text='metres',
        validators=[MinValueValidator(Decimal('2')), MaxValueValidator(Decimal('6'))],
    )

    roof_type = models.CharField(max_length=30, choices=ROOF_TYPE_CHOICES)
    roof_pitch = models.DecimalField(
        max_digits=4, decimal_places=1, help_text='degrees',
        validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('60'))],
    )
    truss_type = models.CharField(max_length=10, choices=TRUSS_TYPE_CHOICES)

    floor_finish = models.CharField(max_length=20, choices=FLOOR_FINISH_CHOICES)
    wall_finish = models.CharField(max_length=20, choices=WALL_FINISH_CHOICES)
    ceiling_type = models.CharField(max_length=20, choices=CEILING_TYPE_CHOICES)

    electrical_package = models.CharField(max_length=20, choices=ELECTRICAL_PACKAGE_CHOICES)
    water_supply = models.CharField(max_length=20, choices=WATER_SUPPLY_CHOICES)
    additional_services = models.JSONField(default=list, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Spec for {self.project.name}'


BAR_SIZE_CHOICES = [
    ('y8', 'Y8'),
    ('y10', 'Y10'),
    ('y12', 'Y12'),
    ('y16', 'Y16'),
    ('y20', 'Y20'),
    ('y25', 'Y25'),
    ('y32', 'Y32'),
]


class StructuralMember(models.Model):
    MEMBER_TYPE_CHOICES = [
        ('column', 'Column'),
        ('beam', 'Beam'),
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='structural_members')
    member_type = models.CharField(max_length=10, choices=MEMBER_TYPE_CHOICES)
    label = models.CharField(max_length=20, help_text='e.g. C1, B1')
    size = models.CharField(max_length=30, help_text='e.g. 225x225')
    length_m = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal('0.3')), MaxValueValidator(Decimal('20'))],
        help_text='Column height or beam span, in metres. Leave blank to fall back to wall height (columns) '
                   'or a flat 4m assumed span (beams) — filling this in gives a more accurate concrete/formwork volume.',
    )
    quantity_count = models.PositiveIntegerField()

    def __str__(self):
        length = f' x {self.length_m}m' if self.length_m else ''
        return f'{self.label} ({self.get_member_type_display()} {self.size}{length}) x{self.quantity_count}'


class ReinforcementSpec(models.Model):
    ELEMENT_CHOICES = [
        ('foundation', 'Foundation'),
        ('slab', 'Slab'),
        ('column', 'Column'),
        ('beam', 'Beam'),
    ]
    BAR_ROLE_CHOICES = [
        ('main', 'Main'),
        ('distribution', 'Distribution'),
        ('stirrup', 'Stirrup/Link'),
    ]
    SLAB_FOUNDATION_ROLES = {'main', 'distribution'}
    COLUMN_BEAM_ROLES = {'main', 'stirrup'}

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='reinforcement_specs')
    element = models.CharField(max_length=20, choices=ELEMENT_CHOICES)
    structural_member = models.ForeignKey(
        StructuralMember, on_delete=models.CASCADE, null=True, blank=True,
        related_name='reinforcement_specs',
        help_text='Which labeled member (e.g. C1, B1) this row applies to. Required for Column/Beam rows; leave blank for Foundation/Slab.',
    )
    bar_role = models.CharField(max_length=20, choices=BAR_ROLE_CHOICES)
    bar_size = models.CharField(max_length=10, choices=BAR_SIZE_CHOICES)
    spacing_mm = models.DecimalField(
        max_digits=6, decimal_places=1,
        validators=[MinValueValidator(Decimal('50')), MaxValueValidator(Decimal('400'))],
        help_text='Stirrup/link spacing when Bar Role is Stirrup; main-bar spacing when Bar Role is Main or Distribution.',
    )

    def clean(self):
        errors = {}

        if self.element in ('column', 'beam'):
            if not self.structural_member_id:
                errors['structural_member'] = (
                    'Required for Column/Beam rows — select which labeled member this schedule applies to.'
                )
            elif self.structural_member.project_id != self.project_id:
                errors['structural_member'] = 'Selected member does not belong to this project.'
            if self.bar_role not in self.COLUMN_BEAM_ROLES:
                errors['bar_role'] = "Columns and beams use Main or Stirrup bars — they don't have distribution bars."
        elif self.element in ('foundation', 'slab'):
            if self.structural_member_id:
                errors['structural_member'] = 'Not applicable for Foundation/Slab rows — leave blank.'
            if self.bar_role not in self.SLAB_FOUNDATION_ROLES:
                errors['bar_role'] = 'Foundation and Slab rows use Main or Distribution bars, not Stirrup.'

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        member = f' [{self.structural_member.label}]' if self.structural_member_id else ''
        return f'{self.get_element_display()}{member} {self.get_bar_role_display()} {self.get_bar_size_display()} @ {self.spacing_mm}mm'
