from django.core.management.base import BaseCommand

from beme.models import MaterialPrice

# (material_name, unit) -> {city: (rate, previous_rate)}
SEED_DATA = {
    ('Cement (50kg bag)', 'bag'): {
        'lagos': (9500, 9200),
        'ibadan': (9200, 9000),
        'abuja': (9800, 9600),
        'port_harcourt': (9600, 9300),
    },
    ('Reinforcement Y8 High Yield', 'kg'): {
        'lagos': (1480, 1430),
        'ibadan': (1430, 1410),
        'abuja': (1530, 1480),
        'port_harcourt': (1510, 1460),
    },
    ('Reinforcement Y10 High Yield', 'kg'): {
        'lagos': (1460, 1410),
        'ibadan': (1410, 1390),
        'abuja': (1510, 1460),
        'port_harcourt': (1490, 1440),
    },
    ('Reinforcement Y12 High Yield', 'kg'): {
        'lagos': (1450, 1400),
        'ibadan': (1400, 1380),
        'abuja': (1500, 1450),
        'port_harcourt': (1480, 1430),
    },
    ('Reinforcement Y16 High Yield', 'kg'): {
        'lagos': (1440, 1390),
        'ibadan': (1390, 1370),
        'abuja': (1490, 1440),
        'port_harcourt': (1470, 1420),
    },
    ('Reinforcement Y20 High Yield', 'kg'): {
        'lagos': (1430, 1380),
        'ibadan': (1380, 1360),
        'abuja': (1480, 1430),
        'port_harcourt': (1460, 1410),
    },
    ('Reinforcement Y25 High Yield', 'kg'): {
        'lagos': (1430, 1380),
        'ibadan': (1380, 1360),
        'abuja': (1480, 1430),
        'port_harcourt': (1460, 1410),
    },
    ('Reinforcement Y32 High Yield', 'kg'): {
        'lagos': (1420, 1370),
        'ibadan': (1370, 1350),
        'abuja': (1470, 1420),
        'port_harcourt': (1450, 1400),
    },
    ('Sharp Sand', 'ton'): {
        'lagos': (18000, 17000),
        'ibadan': (15000, 14500),
        'abuja': (16500, 16000),
        'port_harcourt': (17000, 16800),
    },
    ('Granite Chippings', 'ton'): {
        'lagos': (25000, 24000),
        'ibadan': (22000, 21500),
        'abuja': (24000, 23500),
        'port_harcourt': (26000, 25000),
    },
    ('9-inch Sandcrete Block', 'No'): {
        'lagos': (650, 600),
        'ibadan': (550, 520),
        'abuja': (600, 580),
        'port_harcourt': (620, 600),
    },
    ('Long Span Aluminium Roofing Sheet', 'm²'): {
        'lagos': (8500, 8200),
        'ibadan': (8000, 7800),
        'abuja': (8800, 8500),
        'port_harcourt': (8600, 8400),
    },
    ('Binding Wire', 'kg'): {
        'lagos': (2200, 2100),
        'ibadan': (2100, 2050),
        'abuja': (2300, 2200),
        'port_harcourt': (2250, 2200),
    },
    ('Emulsion Paint (20L bucket)', 'bucket'): {
        'lagos': (45000, 43000),
        'ibadan': (40000, 39000),
        'abuja': (43000, 42000),
        'port_harcourt': (44000, 43500),
    },
}


def _city_rates(lagos_rate, ibadan_factor=0.93, abuja_factor=1.05, port_harcourt_factor=0.98, recent_change=0.04):
    """Derive a 4-city (rate, previous_rate) set from one Lagos base rate.

    Mirrors the directional pattern of the hand-seeded materials above: Ibadan
    cheapest, Abuja priciest, Port Harcourt close to Lagos, all up slightly
    from a `previous_rate` to drive the live-price change indicator.
    """
    factors = {'lagos': 1.0, 'ibadan': ibadan_factor, 'abuja': abuja_factor, 'port_harcourt': port_harcourt_factor}
    return {
        city: (round(lagos_rate * factor), round(lagos_rate * factor / (1 + recent_change)))
        for city, factor in factors.items()
    }


# Composite/work rates consumed by the BEME generation engine (beme/services.py) —
# these price whole trade operations (e.g. "cast m³ of reinforced concrete"),
# not raw materials, to match how line items read on a real Nigerian BEME.
ENGINE_SEED_DATA = {
    ('Excavation in Foundation Trenches (mechanical)', 'm³'): _city_rates(4200),
    ('Hardcore Filling and Ramming', 'm³'): _city_rates(13000),
    ('Mass Concrete 1:3:6 (Blinding)', 'm³'): _city_rates(58000),
    ('Concrete Grade 15 (1:3:6)', 'm³'): _city_rates(70000),
    ('Concrete Grade 20 (1:2:4)', 'm³'): _city_rates(82000),
    ('Concrete Grade 25 (1:1.5:3)', 'm³'): _city_rates(92000),
    ('Concrete Grade 30 (1:1:2)', 'm³'): _city_rates(105000),
    ('Concrete Grade 35 (1:1:2 High Strength)', 'm³'): _city_rates(120000),
    ('Formwork to Concrete Edges', 'm²'): _city_rates(5200),
    ('Aluminium Sliding Window', 'm²'): _city_rates(32000),
    ('Flush Door with Frame and Ironmongery', 'No'): _city_rates(55000),
    ('Terrazzo Floor Finish', 'm²'): _city_rates(18000),
    ('Ceramic Floor Tiles (600x600mm)', 'm²'): _city_rates(9500),
    ('Cement Screed Floor Finish', 'm²'): _city_rates(3500),
    ('Wood/Laminate Flooring', 'm²'): _city_rates(14000),
    ('Cement-Sand Wall Plaster (Two Coats)', 'm²'): _city_rates(3600),
    ('Textured Wall Coating', 'm²'): _city_rates(6500),
    ('Wallpaper Finish', 'm²'): _city_rates(9000),
    ('POP Suspended Ceiling', 'm²'): _city_rates(7200),
    ('Plywood Ceiling', 'm²'): _city_rates(6000),
    ('Gypsum Board Ceiling', 'm²'): _city_rates(8000),
    ('Aluminium Step Tile Roofing Sheet', 'm²'): _city_rates(11000),
    ('Asbestos Roofing Sheet', 'm²'): _city_rates(5500),
    ('Stone-Coated Tile Roofing Sheet', 'm²'): _city_rates(13500),
    ('Timber Roof Truss and Structure', 'm²'): _city_rates(9800),
    ('Steel Roof Truss and Structure', 'm²'): _city_rates(13000),
    ('Blockwork - 225mm Sandcrete (incl. mortar)', 'm²'): _city_rates(7800),
    ('Blockwork - 150mm Sandcrete (incl. mortar)', 'm²'): _city_rates(6200),
    ('Brick Walling (incl. mortar)', 'm²'): _city_rates(11000),
    ('Drywall Partition', 'm²'): _city_rates(9500),
    ('Standard Electrical Installation Allowance', 'm²'): _city_rates(4200),
    ('Premium Electrical Installation Allowance (Solar-Ready)', 'm²'): _city_rates(7500),
    ('Plumbing Installation Allowance (per Wet Room)', 'No'): _city_rates(380000),
    ('Borehole Drilling and Casing', 'No'): _city_rates(1800000),
}

SEED_DATA.update(ENGINE_SEED_DATA)


class Command(BaseCommand):
    help = 'Seed MaterialPrice with realistic Nigerian rates for Lagos, Ibadan, Abuja, and Port Harcourt.'

    def handle(self, *args, **options):
        created_count = 0
        updated_count = 0

        for (material_name, unit), city_rates in SEED_DATA.items():
            for city, (rate, previous_rate) in city_rates.items():
                obj, created = MaterialPrice.objects.update_or_create(
                    city=city,
                    material_name=material_name,
                    defaults={'unit': unit, 'rate': rate, 'previous_rate': previous_rate},
                )
                if created:
                    created_count += 1
                else:
                    updated_count += 1

        self.stdout.write(self.style.SUCCESS(f'Seeded material prices: {created_count} created, {updated_count} updated.'))
