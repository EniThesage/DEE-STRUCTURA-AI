from decimal import Decimal, ROUND_HALF_UP

from django.db import models

from projects.models import Project


class MaterialPrice(models.Model):
    city = models.CharField(max_length=20, choices=Project.CITY_CHOICES)
    material_name = models.CharField(max_length=100)
    unit = models.CharField(max_length=20)
    rate = models.DecimalField(max_digits=12, decimal_places=2)
    previous_rate = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    date_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['material_name', 'city']
        unique_together = ['city', 'material_name']

    def __str__(self):
        return f'{self.material_name} ({self.get_city_display()})'

    @property
    def change_percent(self):
        if not self.previous_rate:
            return None
        return ((self.rate - self.previous_rate) / self.previous_rate) * 100


class BEMEElement(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='beme_elements')
    element_number = models.PositiveIntegerField()
    title = models.CharField(max_length=100)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order']

    def __str__(self):
        return f'Element {self.element_number} - {self.title}'

    @property
    def total(self):
        return self.line_items.filter(is_section_header=False).aggregate(
            total=models.Sum('amount')
        )['total'] or Decimal('0')


class BEMELineItem(models.Model):
    element = models.ForeignKey(BEMEElement, on_delete=models.CASCADE, related_name='line_items')
    item_label = models.CharField(max_length=5, blank=True)
    description = models.CharField(max_length=255)
    qty = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    unit = models.CharField(max_length=20, blank=True)
    rate = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    amount = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    is_section_header = models.BooleanField(default=False)
    is_provisional_sum = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order']

    def __str__(self):
        return self.description

    def save(self, *args, **kwargs):
        if not self.is_section_header and self.qty is not None and self.rate is not None:
            self.amount = (self.qty * self.rate).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        super().save(*args, **kwargs)


class BEMEDocument(models.Model):
    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name='beme_document')
    generated_at = models.DateTimeField(auto_now=True)

    grand_total = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    preliminaries = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    contract_sum = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    preliminaries_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('10.00'))
    contingency_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('5.00'))
    professional_fees_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('7.50'))
    vat_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('7.50'))

    letterhead_company = models.CharField(max_length=200, blank=True)
    letterhead_address = models.CharField(max_length=255, blank=True)
    letterhead_phone = models.CharField(max_length=50, blank=True)
    letterhead_email = models.EmailField(blank=True)
    letterhead_color = models.CharField(max_length=20, blank=True, default='#1f7a40')
    prepared_by = models.CharField(max_length=200, blank=True)
    reference_number = models.CharField(max_length=50, blank=True)

    def __str__(self):
        return f'BOQ for {self.project.name}'

    @property
    def subtotal_with_preliminaries(self):
        return self.grand_total + self.preliminaries

    @property
    def contingency_amount(self):
        return self.subtotal_with_preliminaries * self.contingency_percent / Decimal('100')

    @property
    def professional_fees_amount(self):
        return self.subtotal_with_preliminaries * self.professional_fees_percent / Decimal('100')

    @property
    def vat_amount(self):
        base = self.subtotal_with_preliminaries + self.contingency_amount + self.professional_fees_amount
        return base * self.vat_percent / Decimal('100')
