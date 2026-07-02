import math
import re
import string
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction

from .models import BEMEDocument, BEMEElement, BEMELineItem, MaterialPrice

WET_ROOM_KEYWORDS = ('toilet', 'bath', 'kitchen', 'wc', 'laundry')

# Standard BS4449 high-yield rebar unit weights, kg per linear metre.
BAR_UNIT_WEIGHT_KG_PER_M = {
    'y8': Decimal('0.395'),
    'y10': Decimal('0.617'),
    'y12': Decimal('0.888'),
    'y16': Decimal('1.578'),
    'y20': Decimal('2.466'),
    'y25': Decimal('3.853'),
    'y32': Decimal('6.313'),
}

BEAM_DEFAULT_SPAN_M = Decimal('4.0')  # assumed average span when only a beam count is given, not a layout
FOOTING_ASSUMED_DEPTH_M = Decimal('0.225')  # used only to convert a foundation reinforcement schedule to kg/m³

# Standard opening sizes used to deduct door/window area from gross wall
# area, once real door/window counts are confirmed per room (Review Rooms
# page) — replaces a flat "15% of gross wall area" opening guess.
DOOR_AREA_M2 = Decimal('2.10')  # ~1.0m x 2.1m single door
WINDOW_AREA_M2 = Decimal('1.44')  # ~1.2m x 1.2m standard window

ROOF_MATERIAL_BY_TYPE = {
    'long_span_aluminum': 'Long Span Aluminium Roofing Sheet',
    'aluminum_step_tile': 'Aluminium Step Tile Roofing Sheet',
    'asbestos': 'Asbestos Roofing Sheet',
    'stone_coated_tile': 'Stone-Coated Tile Roofing Sheet',
}

TRUSS_MATERIAL_BY_TYPE = {
    'timber': 'Timber Roof Truss and Structure',
    'steel': 'Steel Roof Truss and Structure',
}

WALL_MATERIAL_BY_TYPE = {
    'sandcrete_225': 'Blockwork - 225mm Sandcrete (incl. mortar)',
    'sandcrete_150': 'Blockwork - 150mm Sandcrete (incl. mortar)',
    'brick': 'Brick Walling (incl. mortar)',
    'drywall': 'Drywall Partition',
}

FLOOR_FINISH_MATERIAL = {
    'terrazzo': 'Terrazzo Floor Finish',
    'tiles': 'Ceramic Floor Tiles (600x600mm)',
    'screed': 'Cement Screed Floor Finish',
    'wood': 'Wood/Laminate Flooring',
}

WALL_FINISH_TOPCOAT_MATERIAL = {
    'texture': 'Textured Wall Coating',
    'wallpaper': 'Wallpaper Finish',
}

CEILING_MATERIAL = {
    'pop': 'POP Suspended Ceiling',
    'plywood': 'Plywood Ceiling',
    'gypsum': 'Gypsum Board Ceiling',
}

ELECTRICAL_MATERIAL = {
    'standard': 'Standard Electrical Installation Allowance',
    'premium': 'Premium Electrical Installation Allowance (Solar-Ready)',
}

# Raw materials concrete/blockwork/plaster are priced from, rather than a
# single bundled "Concrete Grade X" rate — matches how this app's users
# actually keep their price book (raw cement/sand/granite/blocks), not an
# all-in composite rate per m³/m² that doesn't correspond to anything in
# their admin-managed MaterialPrice table.
RAW_CEMENT_MATERIAL = 'Dangote Cement (50kg bag)'
RAW_SAND_MATERIAL = 'Sharp Sand'
RAW_GRANITE_MATERIAL = 'Granite Chippings'
RAW_TILE_MATERIAL = 'Floor tile 60x60'
TILE_COVERAGE_M2 = Decimal('0.36')  # one 600x600mm tile
TILE_WASTAGE_FACTOR = Decimal('1.10')  # 10% cutting/breakage allowance

RAW_BLOCK_MATERIAL_BY_TYPE = {
    'sandcrete_225': '9-inch Sandcrete Block',
    'sandcrete_150': '6-inch Sandcrete block',
}

# Standard Nigerian QS yield per m³ of cast concrete, by mix ratio — cement in
# 50kg bags, sand/granite in tons (~1.6 t/m³ sand, ~1.5 t/m³ granite bulk
# density). Approximate reference figures, consistent with the rest of this
# engine's "structure correctness matters more than estimation precision"
# approach (see build status notes) — not a substitute for a real mix design.
CONCRETE_MIX_YIELD = {
    'c15': {'cement_bags': Decimal('3.60'), 'sand_ton': Decimal('0.78'), 'granite_ton': Decimal('1.47')},  # 1:3:6
    'c20': {'cement_bags': Decimal('6.40'), 'sand_ton': Decimal('0.72'), 'granite_ton': Decimal('1.35')},  # 1:2:4
    'c25': {'cement_bags': Decimal('7.50'), 'sand_ton': Decimal('0.67'), 'granite_ton': Decimal('1.26')},  # 1:1.5:3
    'c30': {'cement_bags': Decimal('9.00'), 'sand_ton': Decimal('0.56'), 'granite_ton': Decimal('1.05')},  # 1:1:2
    'c35': {'cement_bags': Decimal('10.00'), 'sand_ton': Decimal('0.51'), 'granite_ton': Decimal('0.98')},  # 1:1:2 high strength
}

BLOCKS_PER_M2 = Decimal('10')  # standard allowance: 450x225mm block face + mortar joints (same for 6" and 9")
BLOCK_MORTAR_CEMENT_BAGS_PER_M2 = Decimal('0.25')  # jointing mortar, 1:6 mix
BLOCK_MORTAR_SAND_TON_PER_M2 = Decimal('0.045')

PLASTER_CEMENT_BAGS_PER_M2 = Decimal('0.16')  # cement-sand plaster 1:4, two coats, ~15mm
PLASTER_SAND_TON_PER_M2 = Decimal('0.022')

# Binding wire is rarely priced as its own catalogue item — costed as a small
# allowance against the reinforcement it ties, rather than requiring a
# separate "Binding Wire" MaterialPrice row that may not exist.
BINDING_WIRE_PERCENT_OF_STEEL_COST = Decimal('1.5')

REINFORCEMENT_MATERIAL_BY_SIZE = {
    'y8': 'Reinforcement Y8 High Yield',
    'y10': 'Reinforcement Y10 High Yield',
    'y12': 'Reinforcement Y12 High Yield',
    'y16': 'Reinforcement Y16 High Yield',
    'y20': 'Reinforcement Y20 High Yield',
    'y25': 'Reinforcement Y25 High Yield',
    'y32': 'Reinforcement Y32 High Yield',
}

# Used when an element (foundation/column/beam) has no reinforcement schedule
# row at all, so there's no bar size to read from the project's spec. The
# _FLAG variant is substituted into the line item description so an engineer
# reading the BEME can see at a glance that this figure is a guess, not a
# measured schedule, rather than it silently looking like a real entry.
DEFAULT_BAR_SIZE_CODE = 'y12'
DEFAULT_BAR_SIZE_LABEL = 'Y12'
DEFAULT_BAR_SIZE_FLAG = 'Y12 — default, no schedule entered, verify'

ADDITIONAL_SERVICE_ALLOWANCE = {
    'solar': ('Solar power system supply and installation', Decimal('1800000')),
    'cctv': ('CCTV security system supply and installation', Decimal('650000')),
    'fire_protection': ('Fire protection system (extinguishers, smoke detectors)', Decimal('450000')),
    'generator': ('Generator backup supply and installation', Decimal('2200000')),
    'borehole_treatment': ('Borehole water treatment system', Decimal('500000')),
    'intercom': ('Intercom system supply and installation', Decimal('300000')),
}

PAINT_COVERAGE_PER_BUCKET = Decimal('40')  # m² per 20L bucket, two coats
ELEMENT_PAGE_SIZE = 25  # rows per page before a "Carried to Collection" break


class BEMEGenerationError(Exception):
    pass


def paginate_element(element):
    """Split an element's line items into page-sized chunks for the BEME
    document's "Carried to Collection" / "COLLECTION" pagination convention.
    """
    lines = list(element.line_items.all())
    chunks = [lines[i:i + ELEMENT_PAGE_SIZE] for i in range(0, len(lines), ELEMENT_PAGE_SIZE)] or [[]]

    pages = []
    for number, page_lines in enumerate(chunks, start=1):
        subtotal = sum(
            (line.amount for line in page_lines if not line.is_section_header and line.amount is not None),
            Decimal('0'),
        )
        pages.append({
            'number': number,
            'code': f'E{element.element_number}/{number}',
            'lines': page_lines,
            'subtotal': subtotal,
        })
    return pages


def _money(value):
    return Decimal(value).quantize(Decimal('1'), rounding=ROUND_HALF_UP)


def _qty(value):
    return Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _ceil_decimal(value):
    return Decimal(math.ceil(value))


def _provisional_item(description, reason):
    """A line item for a quantity that genuinely can't be calculated yet —
    the required input was never extracted, confirmed, or answered. Amount is
    left blank (not guessed) so it's visibly unpriced until the engineer
    either supplies the missing input and regenerates, or prices it directly
    on the Edit Line Items page."""
    return {
        'description': description,
        'unit': 'sum',
        'amount': None,
        'is_provisional_sum': True,
        'formula': 'Not calculated — see source note.',
        'source': reason,
    }


def _parse_size_to_area_m2(size):
    """Parse a free-text member size like "225x225" or "225 x 450mm" into m².
    Returns None if it can't be parsed (caller should fall back to a flat ratio)."""
    numbers = re.findall(r'\d+(?:\.\d+)?', size or '')
    if len(numbers) < 2:
        return None
    width_mm, depth_mm = Decimal(numbers[0]), Decimal(numbers[1])
    return (width_mm * depth_mm) / Decimal('1000000')


def _mesh_density_kg_per_m3(reinforcement_specs, element, thickness_m):
    """Reinforcement density for a slab/footing mesh, from a Main+Distribution
    bar schedule at given spacings — kg/m² per layer (unit_weight / spacing),
    summed across roles, divided by member thickness. Returns None if no rows
    are tagged for this element (caller falls back to a flat kg/m³ ratio)."""
    rows = [r for r in reinforcement_specs if r.element == element]
    if not rows or thickness_m <= 0:
        return None

    kg_per_m2 = Decimal('0')
    for row in rows:
        unit_weight = BAR_UNIT_WEIGHT_KG_PER_M.get(row.bar_size)
        if not unit_weight or not row.spacing_mm:
            continue
        spacing_m = row.spacing_mm / Decimal('1000')
        kg_per_m2 += unit_weight / spacing_m

    if kg_per_m2 == 0:
        return None
    return kg_per_m2 / thickness_m


def _member_bar_size_display(reinforcement_specs, elements):
    """Most specific bar size chosen for columns/beams, for the line item
    description only — column/beam reinforcement is link-spaced, not a mesh,
    so it doesn't feed the density calculation."""
    for row in reinforcement_specs:
        if row.element in elements:
            return row.get_bar_size_display()
    return None


def _member_bar_size_code(reinforcement_specs, elements):
    """Same lookup as _member_bar_size_display but returns the raw choice
    code (e.g. 'y16'), for selecting the matching MaterialPrice rate."""
    for row in reinforcement_specs:
        if row.element in elements:
            return row.bar_size
    return None


def _concrete_material_lines(volume_m3, grade, rate_for, context):
    """Decompose a concrete volume into raw cement/sand/granite line items
    via standard mix-ratio yields, instead of one bundled "Concrete Grade X"
    rate that doesn't correspond to anything in the user's price book."""
    yields = CONCRETE_MIX_YIELD[grade]
    return [
        {
            'description': f'Cement to {context}',
            'qty': _qty(volume_m3 * yields['cement_bags']), 'unit': 'bag', 'rate': rate_for(RAW_CEMENT_MATERIAL),
        },
        {
            'description': f'Sharp sand to {context}',
            'qty': _qty(volume_m3 * yields['sand_ton']), 'unit': 'ton', 'rate': rate_for(RAW_SAND_MATERIAL),
        },
        {
            'description': f'Granite chippings to {context}',
            'qty': _qty(volume_m3 * yields['granite_ton']), 'unit': 'ton', 'rate': rate_for(RAW_GRANITE_MATERIAL),
        },
    ]


def _blockwork_material_lines(wall_area_m2, block_material_name, context, rate_for):
    """Decompose a blockwork area into raw block count + jointing mortar
    (cement + sand), instead of one bundled "Blockwork ... (incl. mortar)"
    rate that doesn't correspond to anything in the user's price book."""
    return [
        {
            'description': f'{block_material_name} to {context}',
            'qty': _qty(wall_area_m2 * BLOCKS_PER_M2), 'unit': 'No', 'rate': rate_for(block_material_name),
        },
        {
            'description': f'Mortar cement to {context}',
            'qty': _qty(wall_area_m2 * BLOCK_MORTAR_CEMENT_BAGS_PER_M2), 'unit': 'bag',
            'rate': rate_for(RAW_CEMENT_MATERIAL),
        },
        {
            'description': f'Mortar sand to {context}',
            'qty': _qty(wall_area_m2 * BLOCK_MORTAR_SAND_TON_PER_M2), 'unit': 'ton',
            'rate': rate_for(RAW_SAND_MATERIAL),
        },
    ]


def _plaster_material_lines(plaster_area_m2, rate_for):
    """Decompose wall plaster into raw cement + sand, instead of one bundled
    "Cement-Sand Wall Plaster" rate that doesn't correspond to anything in
    the user's price book."""
    return [
        {
            'description': 'Cement for wall plaster (1:4, two coats)',
            'qty': _qty(plaster_area_m2 * PLASTER_CEMENT_BAGS_PER_M2), 'unit': 'bag',
            'rate': rate_for(RAW_CEMENT_MATERIAL),
        },
        {
            'description': 'Sharp sand for wall plaster (1:4, two coats)',
            'qty': _qty(plaster_area_m2 * PLASTER_SAND_TON_PER_M2), 'unit': 'ton',
            'rate': rate_for(RAW_SAND_MATERIAL),
        },
    ]


def _floor_tile_line(area_m2, rate_for):
    tile_count = (area_m2 / TILE_COVERAGE_M2) * TILE_WASTAGE_FACTOR
    return {
        'description': '600x600mm floor tiles to floors (incl. 10% wastage)',
        'qty': _qty(tile_count), 'unit': 'No', 'rate': rate_for(RAW_TILE_MATERIAL),
    }


def _reinforcement_line(description, kg_qty, bar_code, material_for):
    """Reinforcement is priced by whatever unit the user actually set per bar
    size — this catalogue mixes Ton-priced and per-metre-priced bars across
    sizes (observed directly in the seeded data), so the computed kg
    quantity is converted into whatever unit the rate is quoted in, rather
    than assuming one fixed unit for every bar size. Returns (line_item,
    amount) — the amount is needed by the caller to cost the binding-wire
    allowance as a percentage of reinforcement cost."""
    name = REINFORCEMENT_MATERIAL_BY_SIZE[bar_code]
    mp = material_for(name)
    unit = (mp.unit or '').strip().lower()
    if unit in ('ton', 'tonne', 'tonnes'):
        qty = kg_qty / Decimal('1000')
    elif unit == 'm':
        bar_weight = BAR_UNIT_WEIGHT_KG_PER_M.get(bar_code)
        qty = kg_qty / bar_weight if bar_weight else kg_qty
    else:
        qty = kg_qty
    amount = _money(qty * mp.rate)
    line_item = {'description': description, 'qty': _qty(qty), 'unit': mp.unit or 'kg', 'rate': mp.rate}
    return line_item, amount


def generate_beme(project):
    if project.drawings.filter(discipline='architectural', reviewed=False).exists():
        raise BEMEGenerationError(
            'Review and confirm the extracted rooms on the Review Rooms page before generating a BOQ.'
        )

    rooms = list(project.rooms.all())
    if not rooms:
        raise BEMEGenerationError('Add rooms to this project before generating a BOQ.')

    spec = getattr(project, 'spec', None)
    if spec is None:
        raise BEMEGenerationError('Complete the project specification before generating a BOQ.')

    materials = {mp.material_name: mp for mp in MaterialPrice.objects.filter(city=project.location)}

    def material_for(name):
        if name not in materials:
            raise BEMEGenerationError(
                f'No seeded price for "{name}" in {project.get_location_display()}. '
                'Seed material prices for this city before generating a BOQ.'
            )
        return materials[name]

    def rate_for(name):
        return material_for(name).rate

    reinforcement_specs = list(project.reinforcement_specs.all())
    structural_members = list(project.structural_members.all())

    metrics = _compute_metrics(rooms, spec)
    elements_data = [
        (1, 'Substructure', _substructure_items(spec, metrics, rate_for, material_for, reinforcement_specs)),
        (2, 'Superstructure / Concrete Work',
         _superstructure_items(spec, metrics, rate_for, material_for, reinforcement_specs, structural_members)),
        (3, 'Block Work', _blockwork_items(spec, metrics, rate_for)),
        (4, 'Roof', _roof_items(spec, metrics, rate_for)),
        (5, 'Windows', _windows_items(metrics, rate_for)),
        (6, 'Doors', _doors_items(metrics, rate_for)),
        (7, 'Finishings', _finishings_items(spec, metrics, rate_for)),
        (8, 'Plumbing/Mechanical Installations', _plumbing_items(spec, metrics, rate_for)),
        (9, 'Electrical Installation', _electrical_items(spec, metrics, rate_for)),
        (10, 'Painting and Decoration', _painting_items(spec, metrics, rate_for)),
        (11, 'Additional Services', _additional_services_items(spec)),
    ]
    # An element with no line items (e.g. no wet rooms means nothing to plumb,
    # a single-room project has no internal partitions to paint) shouldn't
    # appear in the document at all.
    elements_data = [entry for entry in elements_data if entry[2]]

    return _persist_beme(project, elements_data)


def _compute_metrics(rooms, spec):
    total_area = sum((room.area for room in rooms), Decimal('0'))
    room_count = len(rooms)
    # No `max(1, ...)` floor here — a room with no kitchen/bathroom/toilet
    # genuinely has zero wet-room plumbing scope (e.g. a standalone sitting room).
    wet_room_count = sum(1 for room in rooms if any(k in room.name.lower() for k in WET_ROOM_KEYWORDS))

    # Perimeter only comes from a confirmed footprint (set on the Review Rooms
    # page, usually pre-filled from floor plan extraction). No aspect-ratio
    # estimate fallback — a guessed footprint is exactly the kind of
    # fabricated base quantity this engine no longer produces. Every
    # perimeter-dependent item below routes to a provisional sum instead when
    # this is None.
    project = spec.project
    if project.footprint_width_m and project.footprint_length_m:
        perimeter = 2 * (project.footprint_width_m + project.footprint_length_m)
        perimeter_source = f'confirmed footprint {project.footprint_width_m}m x {project.footprint_length_m}m'
    else:
        perimeter = None
        perimeter_source = None

    # Door/window counts come from confirmed Room fields (extracted, then
    # reviewed/edited on the Review Rooms page) rather than a "1 opening per
    # room" guess. A combined total of 0 means the counts were never
    # populated or confirmed — treated as unconfirmed, not as "this building
    # genuinely has no doors or windows".
    door_count = sum(room.door_count for room in rooms)
    window_count = sum(room.window_count for room in rooms)
    openings_confirmed = (door_count + window_count) > 0
    openings_area = (Decimal(door_count) * DOOR_AREA_M2) + (Decimal(window_count) * WINDOW_AREA_M2)

    wall_height = spec.wall_height
    if perimeter is not None:
        gross_external_wall_area = perimeter * wall_height
        external_wall_area = gross_external_wall_area - (openings_area if openings_confirmed else Decimal('0'))
    else:
        external_wall_area = None

    # Internal partition wall length has no confirmed source yet — interior
    # wall extraction isn't built until a later phase, and there's no wizard
    # question for it either. Always provisional now, never a ratio guess.
    internal_wall_area = None

    roof_pitch_deg = min(float(spec.roof_pitch), 60.0)
    roof_slope_factor = Decimal(str(1 / math.cos(math.radians(roof_pitch_deg))))
    roof_area = total_area * roof_slope_factor * Decimal('1.15')  # 15% eaves/overhang allowance, on confirmed area

    return {
        'total_area': total_area,
        'room_count': room_count,
        'wet_room_count': wet_room_count,
        'perimeter': perimeter,
        'perimeter_source': perimeter_source,
        'wall_height': wall_height,
        'external_wall_area': external_wall_area,
        'internal_wall_area': internal_wall_area,
        'roof_area': roof_area,
        'door_count': door_count,
        'window_count': window_count,
        'openings_confirmed': openings_confirmed,
        'openings_area': openings_area,
    }


FOUNDATION_VOLUME_PER_METRE = {
    'strip': Decimal('0.30'),
    'pad': Decimal('0.21'),
    'pile': Decimal('0.25'),
}


def _substructure_items(spec, metrics, rate_for, material_for, reinforcement_specs):
    perimeter = metrics['perimeter']
    perimeter_source = metrics['perimeter_source']
    total_area = metrics['total_area']
    trench_width = Decimal('0.6')

    items = [{'description': 'Excavation & Earth Work', 'is_section_header': True}]
    items.append({
        'description': 'Site clearance and setting out',
        'unit': 'sum',
        'amount': _money(total_area * Decimal('500')),
        'is_provisional_sum': True,
        'formula': f'allowance: total floor area {_qty(total_area)}m² x standard ₦500/m²',
        'source': 'total floor area: confirmed rooms',
    })

    if perimeter is not None:
        excavation_volume = perimeter * trench_width * spec.excavation_depth
        items.append({
            'description': f'Excavate foundation trenches to {spec.excavation_depth}m depth',
            'qty': _qty(excavation_volume),
            'unit': 'm³',
            'rate': rate_for('Excavation in Foundation Trenches (mechanical)'),
            'formula': f'perimeter {_qty(perimeter)}m x trench width {trench_width}m x depth {spec.excavation_depth}m '
                       f'= {_qty(excavation_volume)}m³',
            'source': f'perimeter: {perimeter_source}; trench width: standard 0.6m; depth: wizard specification',
        })
    else:
        items.append(_provisional_item(
            'Excavate foundation trenches — provisional',
            'building footprint not confirmed — enter it on Review Rooms and regenerate for a real trench volume',
        ))

    hardcore_volume = total_area * Decimal('0.15')
    items.append({
        'description': 'Hardcore filling and ramming to make up levels, 150mm thick',
        'qty': _qty(hardcore_volume),
        'unit': 'm³',
        'rate': rate_for('Hardcore Filling and Ramming'),
        'formula': f'total floor area {_qty(total_area)}m² x 0.15m thickness = {_qty(hardcore_volume)}m³',
        'source': 'total floor area: confirmed rooms',
    })
    items.append({
        'description': 'Anti-termite treatment to substructure',
        'unit': 'sum',
        'amount': _money(total_area * Decimal('350')),
        'is_provisional_sum': True,
        'formula': f'allowance: total floor area {_qty(total_area)}m² x standard ₦350/m²',
        'source': 'total floor area: confirmed rooms',
    })

    items.append({'description': 'Concrete Work', 'is_section_header': True})
    if perimeter is not None:
        blinding_volume = perimeter * trench_width * Decimal('0.05')
        items.append({
            'description': 'Mass concrete (1:3:6) blinding to foundation',
            'qty': _qty(blinding_volume),
            'unit': 'm³',
            'rate': rate_for('Mass Concrete 1:3:6 (Blinding)'),
            'formula': f'perimeter {_qty(perimeter)}m x trench width {trench_width}m x 0.05m = {_qty(blinding_volume)}m³',
            'source': f'perimeter: {perimeter_source}',
        })
    else:
        items.append(_provisional_item(
            'Mass concrete blinding to foundation — provisional',
            'building footprint not confirmed — perimeter needed for blinding volume',
        ))

    footing_volume = None
    footing_formula = footing_source = None
    if spec.foundation_type == 'raft':
        footing_volume = total_area * Decimal('0.15')
        footing_formula = f'total floor area {_qty(total_area)}m² x 0.15m raft thickness = {_qty(footing_volume)}m³'
        footing_source = 'total floor area: confirmed rooms'
    elif perimeter is not None:
        ratio = FOUNDATION_VOLUME_PER_METRE.get(spec.foundation_type, Decimal('0.30'))
        footing_volume = perimeter * ratio
        footing_formula = (
            f'perimeter {_qty(perimeter)}m x {ratio}m³/m standard {spec.get_foundation_type_display()} yield '
            f'= {_qty(footing_volume)}m³'
        )
        footing_source = f'perimeter: {perimeter_source}'

    if footing_volume is not None:
        concrete_lines = _concrete_material_lines(
            footing_volume, spec.concrete_grade, rate_for,
            context=f'foundation footing ({spec.get_foundation_type_display()}), '
                    f'Grade {spec.get_concrete_grade_display()}',
        )
        for line in concrete_lines:
            line['formula'] = footing_formula
            line['source'] = footing_source
        items += concrete_lines

        density = _mesh_density_kg_per_m3(reinforcement_specs, 'foundation', FOOTING_ASSUMED_DEPTH_M)
        reinforcement_kg = footing_volume * (density if density is not None else Decimal('40'))
        foundation_bar_label = _member_bar_size_display(reinforcement_specs, ('foundation',)) or DEFAULT_BAR_SIZE_FLAG
        foundation_bar_code = _member_bar_size_code(reinforcement_specs, ('foundation',)) or DEFAULT_BAR_SIZE_CODE

        reinforcement_item, reinforcement_amount = _reinforcement_line(
            f'High yield reinforcement bars ({foundation_bar_label}) to foundation',
            reinforcement_kg, foundation_bar_code, material_for,
        )
        density_note = 'confirmed reinforcement schedule' if density is not None else 'standard 40kg/m³ default — verify'
        reinforcement_item['formula'] = f'footing volume {_qty(footing_volume)}m³ x mesh density ({density_note})'
        reinforcement_item['source'] = f'footing volume: see above; reinforcement density: {density_note}'
        binding_wire_amount = _money(reinforcement_amount * BINDING_WIRE_PERCENT_OF_STEEL_COST / Decimal('100'))

        items.append({'description': 'Reinforcement', 'is_section_header': True})
        items.append(reinforcement_item)
        items.append({
            'description': 'Binding wire (allowance, % of reinforcement cost)',
            'unit': 'sum',
            'amount': binding_wire_amount,
            'is_provisional_sum': True,
            'formula': f'{BINDING_WIRE_PERCENT_OF_STEEL_COST}% of reinforcement cost',
            'source': 'reinforcement cost: see above',
        })
    else:
        items.append({'description': 'Reinforcement', 'is_section_header': True})
        items.append(_provisional_item(
            'Foundation concrete and reinforcement — provisional',
            f'building footprint not confirmed — perimeter needed for {spec.get_foundation_type_display()} footing volume',
        ))

    items.append({'description': 'Formwork', 'is_section_header': True})
    if perimeter is not None:
        formwork_area = perimeter * Decimal('0.6')
        items.append({
            'description': 'Formwork to foundation edges',
            'qty': _qty(formwork_area),
            'unit': 'm²',
            'rate': rate_for('Formwork to Concrete Edges'),
            'formula': f'perimeter {_qty(perimeter)}m x 0.6m = {_qty(formwork_area)}m²',
            'source': f'perimeter: {perimeter_source}',
        })
    else:
        items.append(_provisional_item(
            'Formwork to foundation edges — provisional', 'building footprint not confirmed',
        ))

    return items


def _column_beam_volume_from_members(structural_members, wall_height):
    """Real geometry from the project's structural member schedule (size × count
    × length per member), when one was entered. Returns None if there's no
    usable schedule, so the caller can fall back to a flat ratio."""
    if not structural_members:
        return None

    volume = Decimal('0')
    matched_any = False
    for member in structural_members:
        area_m2 = _parse_size_to_area_m2(member.size)
        if area_m2 is None:
            continue
        # A real entered length beats the assumption — especially for beams,
        # where "4m" is just a placeholder average span, not this project's
        # actual one.
        if member.length_m:
            length_m = member.length_m
        else:
            length_m = wall_height if member.member_type == 'column' else BEAM_DEFAULT_SPAN_M
        volume += area_m2 * length_m * member.quantity_count
        matched_any = True

    return volume if matched_any else None


def _superstructure_items(spec, metrics, rate_for, material_for, reinforcement_specs, structural_members):
    total_area = metrics['total_area']
    perimeter = metrics['perimeter']
    framed = spec.frame_type == 'framed'

    column_beam_volume = None
    column_beam_source = None
    if framed:
        column_beam_volume = _column_beam_volume_from_members(structural_members, spec.wall_height)
        if column_beam_volume is not None:
            column_beam_source = 'structural member schedule (size x count x length)'

    slab_thickness_m = spec.slab_thickness / Decimal('1000')
    slab_volume = total_area * slab_thickness_m
    combined_volume = slab_volume + (column_beam_volume or Decimal('0'))

    member_desc = 'columns, beams and suspended floor slab' if column_beam_volume is not None else 'suspended floor slab'
    items = [{'description': 'Concrete Work', 'is_section_header': True}]
    concrete_lines = _concrete_material_lines(
        combined_volume, spec.concrete_grade, rate_for,
        context=f'{member_desc} ({spec.slab_thickness}mm), Grade {spec.get_concrete_grade_display()}',
    )
    formula = f'slab: floor area {_qty(total_area)}m² x {slab_thickness_m}m = {_qty(slab_volume)}m³'
    source = 'floor area: confirmed rooms; slab thickness: wizard'
    if column_beam_volume is not None:
        formula += f'; columns/beams: {_qty(column_beam_volume)}m³ from structural member schedule'
        source += f'; columns/beams: {column_beam_source}'
    for line in concrete_lines:
        line['formula'] = formula
        line['source'] = source
    items += concrete_lines

    if framed and column_beam_volume is None:
        items.append(_provisional_item(
            'Concrete columns and beams — provisional',
            'framed structure selected but no structural member schedule entered — add columns/beams under '
            'Specifications, or this needs pricing separately',
        ))

    slab_density = _mesh_density_kg_per_m3(reinforcement_specs, 'slab', slab_thickness_m)
    slab_reinforcement_kg = slab_volume * (slab_density if slab_density is not None else Decimal('90'))
    reinforcement_kg = slab_reinforcement_kg
    reinforcement_desc = 'slab'
    if column_beam_volume is not None:
        reinforcement_kg += column_beam_volume * Decimal('90')  # link-spaced, not a mesh — flat ratio
        reinforcement_desc = 'columns, beams and slab'

    bar_label = _member_bar_size_display(reinforcement_specs, ('column', 'beam')) or DEFAULT_BAR_SIZE_FLAG
    bar_code = _member_bar_size_code(reinforcement_specs, ('column', 'beam')) or DEFAULT_BAR_SIZE_CODE

    reinforcement_item, reinforcement_amount = _reinforcement_line(
        f'High yield reinforcement bars ({bar_label}) to {reinforcement_desc}',
        reinforcement_kg, bar_code, material_for,
    )
    density_note = 'confirmed reinforcement schedule' if slab_density is not None else 'standard 90kg/m³ default — verify'
    reinforcement_formula = f'slab volume {_qty(slab_volume)}m³ x mesh density ({density_note})'
    if column_beam_volume is not None:
        reinforcement_formula += f' + columns/beams {_qty(column_beam_volume)}m³ x 90kg/m³ standard ratio'
    reinforcement_item['formula'] = reinforcement_formula
    reinforcement_item['source'] = f'slab volume: see above; reinforcement density: {density_note}'
    binding_wire_amount = _money(reinforcement_amount * BINDING_WIRE_PERCENT_OF_STEEL_COST / Decimal('100'))

    items.append({'description': 'Reinforcement', 'is_section_header': True})
    items.append(reinforcement_item)
    items.append({
        'description': 'Binding wire (allowance, % of reinforcement cost)',
        'unit': 'sum',
        'amount': binding_wire_amount,
        'is_provisional_sum': True,
        'formula': f'{BINDING_WIRE_PERCENT_OF_STEEL_COST}% of reinforcement cost',
        'source': 'reinforcement cost: see above',
    })

    items.append({'description': 'Formwork', 'is_section_header': True})
    if framed:
        if column_beam_volume is not None:
            formwork_columns_beams = column_beam_volume * Decimal('8')
            items.append({
                'description': 'Formwork to columns and beams',
                'qty': _qty(formwork_columns_beams),
                'unit': 'm²',
                'rate': rate_for('Formwork to Concrete Edges'),
                'formula': f'columns/beams volume {_qty(column_beam_volume)}m³ x 8m²/m³ standard ratio '
                           f'= {_qty(formwork_columns_beams)}m²',
                'source': 'columns/beams volume: structural member schedule',
            })
        else:
            items.append(_provisional_item(
                'Formwork to columns and beams — provisional',
                'framed structure selected but no structural member schedule entered',
            ))
    if perimeter is not None:
        formwork_slab_edge = perimeter * Decimal('0.15')
        items.append({
            'description': 'Formwork to slab edges',
            'qty': _qty(formwork_slab_edge),
            'unit': 'm²',
            'rate': rate_for('Formwork to Concrete Edges'),
            'formula': f'perimeter {_qty(perimeter)}m x 0.15m = {_qty(formwork_slab_edge)}m²',
            'source': f'perimeter: {metrics["perimeter_source"]}',
        })
    else:
        items.append(_provisional_item('Formwork to slab edges — provisional', 'building footprint not confirmed'))

    return items


def _wall_lines(wall_type, wall_type_display, wall_area_m2, context, rate_for):
    """Sandcrete wall types decompose into blocks + mortar (cement/sand)
    raw materials; other wall types (brick/drywall) aren't in the user's
    raw-material table, so they fall back to a single composite rate."""
    block_material = RAW_BLOCK_MATERIAL_BY_TYPE.get(wall_type)
    if block_material:
        return _blockwork_material_lines(wall_area_m2, block_material, context, rate_for)
    return [{
        'description': f'{wall_type_display} to {context}',
        'qty': _qty(wall_area_m2),
        'unit': 'm²',
        'rate': rate_for(WALL_MATERIAL_BY_TYPE[wall_type]),
    }]


def _blockwork_items(spec, metrics, rate_for):
    items = []
    external_area = metrics['external_wall_area']
    if external_area is not None:
        lines = _wall_lines(
            spec.wall_type_external, spec.get_wall_type_external_display(),
            external_area, 'external walls', rate_for,
        )
        openings_note = (
            f'openings deducted: {metrics["door_count"]} door(s) x {DOOR_AREA_M2}m² + '
            f'{metrics["window_count"]} window(s) x {WINDOW_AREA_M2}m² = {_qty(metrics["openings_area"])}m²'
            if metrics['openings_confirmed'] else 'no door/window counts confirmed — openings not deducted'
        )
        formula = (
            f'perimeter {_qty(metrics["perimeter"])}m x wall height {metrics["wall_height"]}m '
            f'- {_qty(metrics["openings_area"]) if metrics["openings_confirmed"] else Decimal("0")}m² openings '
            f'= {_qty(external_area)}m²'
        )
        for line in lines:
            line['formula'] = formula
            line['source'] = f'perimeter: {metrics["perimeter_source"]}; wall height: wizard; {openings_note}'
        items += lines
    else:
        items.append(_provisional_item(
            'Blockwork in external walls — provisional',
            'building footprint not confirmed — enter it on Review Rooms and regenerate',
        ))

    if metrics['room_count'] > 1:
        items.append(_provisional_item(
            'Blockwork in internal partitions — provisional',
            "interior wall lengths aren't extracted yet — price separately, or check back for a future update "
            "that captures them from a structural/interior drawing",
        ))
    return items


def _roof_items(spec, metrics, rate_for):
    roof_area = metrics['roof_area']
    truss_material = TRUSS_MATERIAL_BY_TYPE[spec.truss_type]
    roofing_material = ROOF_MATERIAL_BY_TYPE[spec.roof_type]
    formula = f'total floor area {_qty(metrics["total_area"])}m² x roof slope factor x 1.15 eaves allowance = {_qty(roof_area)}m²'
    source = 'total floor area: confirmed rooms; roof pitch: wizard'

    return [
        {
            'description': f'{spec.get_truss_type_display()} roof structure',
            'qty': _qty(roof_area),
            'unit': 'm²',
            'rate': rate_for(truss_material),
            'formula': formula,
            'source': source,
        },
        {
            'description': f'{spec.get_roof_type_display()} roof covering',
            'qty': _qty(roof_area),
            'unit': 'm²',
            'rate': rate_for(roofing_material),
            'formula': formula,
            'source': source,
        },
    ]


def _windows_items(metrics, rate_for):
    if not metrics['openings_confirmed']:
        return [_provisional_item(
            'Windows — provisional',
            'no door/window counts confirmed on any room — add them on Review Rooms and regenerate',
        )]
    window_count = metrics['window_count']
    window_area = Decimal(window_count) * WINDOW_AREA_M2
    return [
        {
            'description': 'Supply and install aluminium sliding windows complete with glazing',
            'qty': _qty(window_area),
            'unit': 'm²',
            'rate': rate_for('Aluminium Sliding Window'),
            'formula': f'{window_count} window(s) x {WINDOW_AREA_M2}m² standard size = {_qty(window_area)}m²',
            'source': 'window count: confirmed rooms (Review Rooms page)',
        },
    ]


def _doors_items(metrics, rate_for):
    if not metrics['openings_confirmed']:
        return [_provisional_item(
            'Doors — provisional',
            'no door/window counts confirmed on any room — add them on Review Rooms and regenerate',
        )]
    door_count = metrics['door_count']
    return [
        {
            'description': 'Supply and install flush doors complete with frame and ironmongery',
            'qty': Decimal(door_count),
            'unit': 'No',
            'rate': rate_for('Flush Door with Frame and Ironmongery'),
            'formula': f'{door_count} door(s) confirmed across all rooms',
            'source': 'door count: confirmed rooms (Review Rooms page)',
        },
    ]


def _finishings_items(spec, metrics, rate_for):
    total_area = metrics['total_area']
    ceiling_material = CEILING_MATERIAL[spec.ceiling_type]
    topcoat_material = WALL_FINISH_TOPCOAT_MATERIAL.get(spec.wall_finish)

    items = [{'description': 'Floor Finishes', 'is_section_header': True}]
    if spec.floor_finish == 'tiles':
        floor_line = _floor_tile_line(total_area, rate_for)
        floor_line['formula'] = f'total floor area {_qty(total_area)}m² / {TILE_COVERAGE_M2}m² per tile x {TILE_WASTAGE_FACTOR} wastage'
    else:
        floor_line = {
            'description': f'{spec.get_floor_finish_display()} to floors',
            'qty': _qty(total_area),
            'unit': 'm²',
            'rate': rate_for(FLOOR_FINISH_MATERIAL[spec.floor_finish]),
            'formula': f'total floor area {_qty(total_area)}m²',
        }
    floor_line['source'] = 'total floor area: confirmed rooms'
    items.append(floor_line)

    items.append({'description': 'Wall Finishes', 'is_section_header': True})
    external_area = metrics['external_wall_area']
    if external_area is not None:
        plaster_area = external_area * 2  # both faces of the external wall
        plaster_lines = _plaster_material_lines(plaster_area, rate_for)
        for line in plaster_lines:
            line['formula'] = f'external wall area {_qty(external_area)}m² x 2 faces = {_qty(plaster_area)}m²'
            line['source'] = 'external wall area: see Block Work element'
        items += plaster_lines
        if topcoat_material:
            items.append({
                'description': f'{spec.get_wall_finish_display()} to walls',
                'qty': _qty(plaster_area),
                'unit': 'm²',
                'rate': rate_for(topcoat_material),
                'formula': f'external wall area (both faces) {_qty(plaster_area)}m²',
                'source': 'external wall area: see Block Work element',
            })
    else:
        items.append(_provisional_item('External wall plaster — provisional', 'building footprint not confirmed'))

    if metrics['room_count'] > 1:
        items.append(_provisional_item(
            'Internal wall plaster — provisional',
            "interior wall lengths aren't extracted yet — price separately",
        ))

    items.append({'description': 'Ceiling Finishes', 'is_section_header': True})
    items.append({
        'description': f'{spec.get_ceiling_type_display()} ceiling finish',
        'qty': _qty(total_area),
        'unit': 'm²',
        'rate': rate_for(ceiling_material),
        'formula': f'total floor area {_qty(total_area)}m²',
        'source': 'total floor area: confirmed rooms',
    })
    return items


def _plumbing_items(spec, metrics, rate_for):
    items = []
    if metrics['wet_room_count'] > 0:
        items.append({
            'description': f'Supply and install plumbing fittings and pipework to wet areas '
                           f'({metrics["wet_room_count"]} No)',
            'qty': Decimal(metrics['wet_room_count']),
            'unit': 'No',
            'rate': rate_for('Plumbing Installation Allowance (per Wet Room)'),
            'formula': f'{metrics["wet_room_count"]} wet room(s) (kitchen/bath/toilet/laundry) confirmed',
            'source': 'wet room count: confirmed rooms, matched by name',
        })
    if spec.water_supply in ('borehole', 'both'):
        items.append({
            'description': 'Drill and case borehole complete with submersible pump',
            'qty': Decimal('1'),
            'unit': 'No',
            'rate': rate_for('Borehole Drilling and Casing'),
            'formula': '1 No — water supply option selected',
            'source': 'water supply: wizard specification',
        })
    return items


def _electrical_items(spec, metrics, rate_for):
    electrical_material = ELECTRICAL_MATERIAL[spec.electrical_package]
    return [
        {
            'description': f'Supply and install electrical wiring, distribution board, sockets and fittings '
                           f'({spec.get_electrical_package_display()})',
            'qty': _qty(metrics['total_area']),
            'unit': 'm²',
            'rate': rate_for(electrical_material),
            'formula': f'total floor area {_qty(metrics["total_area"])}m²',
            'source': 'total floor area: confirmed rooms; package: wizard specification',
        },
    ]


def _painting_items(spec, metrics, rate_for):
    paint_rate = rate_for('Emulsion Paint (20L bucket)')
    items = []
    external_area = metrics['external_wall_area']
    if external_area is not None:
        buckets = _ceil_decimal(external_area / PAINT_COVERAGE_PER_BUCKET)
        items.append({
            'description': 'Weatherproof emulsion paint, two coats, to external walls',
            'qty': buckets,
            'unit': 'bucket',
            'rate': paint_rate,
            'formula': f'external wall area {_qty(external_area)}m² / {PAINT_COVERAGE_PER_BUCKET}m² per bucket, '
                       f'rounded up = {buckets} bucket(s)',
            'source': 'external wall area: see Block Work element',
        })
    else:
        items.append(_provisional_item('External wall paint — provisional', 'building footprint not confirmed'))

    if spec.wall_finish == 'paint' and metrics['room_count'] > 1:
        items.append(_provisional_item(
            'Internal wall & ceiling paint — provisional',
            "interior wall lengths aren't extracted yet — price separately",
        ))
    return items


def _additional_services_items(spec):
    items = []
    for service in spec.additional_services:
        description, amount = ADDITIONAL_SERVICE_ALLOWANCE.get(service, (None, None))
        if description is None:
            continue
        items.append({
            'description': description,
            'unit': 'sum',
            'amount': _money(amount),
            'is_provisional_sum': True,
            'formula': 'standard allowance for this service',
            'source': 'additional services: wizard specification',
        })
    return items


@transaction.atomic
def _persist_beme(project, elements_data):
    BEMEElement.objects.filter(project=project).delete()

    for sort_order, (number, title, items) in enumerate(elements_data, start=1):
        element = BEMEElement.objects.create(
            project=project, element_number=number, title=title, sort_order=sort_order
        )
        label_index = 0
        for item_sort, item in enumerate(items, start=1):
            is_header = item.get('is_section_header', False)
            label = ''
            if not is_header:
                label = string.ascii_uppercase[label_index % 26]
                label_index += 1
            BEMELineItem.objects.create(
                element=element,
                item_label=label,
                description=item['description'],
                qty=item.get('qty'),
                unit=item.get('unit', ''),
                rate=item.get('rate'),
                amount=item.get('amount'),
                is_section_header=is_header,
                is_provisional_sum=item.get('is_provisional_sum', False),
                quantity_formula=item.get('formula', ''),
                source_note=item.get('source', ''),
                sort_order=item_sort,
            )

    document, _ = BEMEDocument.objects.get_or_create(project=project)
    return recompute_document_totals(document)


def relabel_element(element):
    """Re-derive each line item's per-element letter (A, B, C... skipping
    section headers) from current sort_order, after a manual edit adds,
    removes, or reorders rows — mirrors the labelling _persist_beme does
    at generation time, but as a standalone step usable after edits.

    Queries BEMELineItem directly rather than via element.line_items —
    if the caller built `element` through a prefetch_related('line_items')
    queryset, the manager's .all() would return that stale cached list
    instead of rows saved earlier in the same request (e.g. a newly added
    line item), silently leaving it unlabelled."""
    label_index = 0
    for item in BEMELineItem.objects.filter(element=element).order_by('sort_order'):
        if item.is_section_header:
            label = ''
        else:
            label = string.ascii_uppercase[label_index % 26]
            label_index += 1
        if item.item_label != label:
            item.item_label = label
            item.save(update_fields=['item_label'])


def recompute_document_totals(document):
    """Re-derive BEMEDocument's stored totals from its elements' line items —
    called both at generation time and after a manual line-item edit, since
    BEMEElement.total is a live DB-backed property but the document's
    grand_total/preliminaries/contract_sum are stored fields that don't
    update themselves."""
    grand_total = sum((element.total for element in document.project.beme_elements.all()), Decimal('0'))
    document.grand_total = grand_total
    document.preliminaries = _money(grand_total * document.preliminaries_percent / Decimal('100'))
    document.contract_sum = _money(
        document.subtotal_with_preliminaries + document.contingency_amount + document.professional_fees_amount
        + document.vat_amount
    )
    document.save()
    return document
