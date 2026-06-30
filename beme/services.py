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

    # Prefer the real footprint (from floor plan extraction, confirmed/edited
    # on the Review Rooms page) for the perimeter used in trench/wall-length
    # ratios. Only fall back to approximating it as a 1.3 length:width
    # rectangle when no footprint has been captured for this project.
    project = spec.project
    if project.footprint_width_m and project.footprint_length_m:
        perimeter = 2 * (project.footprint_width_m + project.footprint_length_m)
    else:
        aspect = Decimal('1.3')
        width_m = (total_area / aspect).sqrt()
        length_m = total_area / width_m
        perimeter = 2 * (length_m + width_m)

    wall_height = spec.wall_height
    gross_external_wall_area = perimeter * wall_height
    external_wall_area = gross_external_wall_area * Decimal('0.85')  # 15% opening deduction

    if room_count > 1:
        internal_wall_length = total_area * Decimal('0.5')  # m of partition per m² floor, rough residential ratio
        internal_wall_area = internal_wall_length * wall_height * Decimal('0.9')  # 10% opening deduction
    else:
        # A single room has no other room to partition from.
        internal_wall_area = Decimal('0')

    roof_pitch_deg = min(float(spec.roof_pitch), 60.0)
    roof_slope_factor = Decimal(str(1 / math.cos(math.radians(roof_pitch_deg))))
    roof_area = total_area * roof_slope_factor * Decimal('1.15')  # 15% eaves/overhang allowance

    # A single-room structure's entrance door doubles as the room door.
    door_count = room_count if room_count <= 1 else room_count + 1

    return {
        'total_area': total_area,
        'room_count': room_count,
        'wet_room_count': wet_room_count,
        'perimeter': perimeter,
        'external_wall_area': external_wall_area,
        'internal_wall_area': internal_wall_area,
        'roof_area': roof_area,
        'door_count': door_count,
        'window_count': room_count,
    }


FOUNDATION_VOLUME_PER_METRE = {
    'strip': Decimal('0.30'),
    'pad': Decimal('0.21'),
    'pile': Decimal('0.25'),
}


def _substructure_items(spec, metrics, rate_for, material_for, reinforcement_specs):
    perimeter = metrics['perimeter']
    total_area = metrics['total_area']
    trench_width = Decimal('0.6')

    excavation_volume = perimeter * trench_width * spec.excavation_depth
    hardcore_volume = total_area * Decimal('0.15')
    blinding_volume = perimeter * trench_width * Decimal('0.05')

    if spec.foundation_type == 'raft':
        footing_volume = total_area * Decimal('0.15')
    else:
        footing_volume = perimeter * FOUNDATION_VOLUME_PER_METRE.get(spec.foundation_type, Decimal('0.30'))

    # Use the project's foundation reinforcement schedule if one was entered
    # (real mesh density from bar size + spacing); otherwise a flat ratio.
    density = _mesh_density_kg_per_m3(reinforcement_specs, 'foundation', FOOTING_ASSUMED_DEPTH_M)
    reinforcement_kg = footing_volume * (density if density is not None else Decimal('40'))
    formwork_area = perimeter * Decimal('0.6')

    foundation_bar_label = _member_bar_size_display(reinforcement_specs, ('foundation',)) or DEFAULT_BAR_SIZE_FLAG
    foundation_bar_code = _member_bar_size_code(reinforcement_specs, ('foundation',)) or DEFAULT_BAR_SIZE_CODE

    reinforcement_item, reinforcement_amount = _reinforcement_line(
        f'High yield reinforcement bars ({foundation_bar_label}) to foundation',
        reinforcement_kg, foundation_bar_code, material_for,
    )
    binding_wire_amount = _money(reinforcement_amount * BINDING_WIRE_PERCENT_OF_STEEL_COST / Decimal('100'))

    items = [
        {'description': 'Excavation & Earth Work', 'is_section_header': True},
        {
            'description': 'Site clearance and setting out',
            'unit': 'sum',
            'amount': _money(total_area * Decimal('500')),
            'is_provisional_sum': True,
        },
        {
            'description': f'Excavate foundation trenches to {spec.excavation_depth}m depth',
            'qty': _qty(excavation_volume),
            'unit': 'm³',
            'rate': rate_for('Excavation in Foundation Trenches (mechanical)'),
        },
        {
            'description': 'Hardcore filling and ramming to make up levels, 150mm thick',
            'qty': _qty(hardcore_volume),
            'unit': 'm³',
            'rate': rate_for('Hardcore Filling and Ramming'),
        },
        {
            'description': 'Anti-termite treatment to substructure',
            'unit': 'sum',
            'amount': _money(total_area * Decimal('350')),
            'is_provisional_sum': True,
        },
        {'description': 'Concrete Work', 'is_section_header': True},
        {
            'description': 'Mass concrete (1:3:6) blinding to foundation',
            'qty': _qty(blinding_volume),
            'unit': 'm³',
            'rate': rate_for('Mass Concrete 1:3:6 (Blinding)'),
        },
    ]
    items += _concrete_material_lines(
        footing_volume, spec.concrete_grade, rate_for,
        context=f'foundation footing ({spec.get_foundation_type_display()}), '
                f'Grade {spec.get_concrete_grade_display()}',
    )
    items += [
        {'description': 'Reinforcement', 'is_section_header': True},
        reinforcement_item,
        {
            'description': 'Binding wire (allowance, % of reinforcement cost)',
            'unit': 'sum',
            'amount': binding_wire_amount,
            'is_provisional_sum': True,
        },
        {'description': 'Formwork', 'is_section_header': True},
        {
            'description': 'Formwork to foundation edges',
            'qty': _qty(formwork_area),
            'unit': 'm²',
            'rate': rate_for('Formwork to Concrete Edges'),
        },
    ]
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

    column_beam_volume = Decimal('0')
    if framed:
        column_beam_volume = _column_beam_volume_from_members(structural_members, spec.wall_height)
        if column_beam_volume is None:
            column_beam_volume = total_area * Decimal('0.04')  # flat fallback ratio

    slab_thickness_m = spec.slab_thickness / Decimal('1000')
    slab_volume = total_area * slab_thickness_m
    total_concrete_volume = column_beam_volume + slab_volume

    slab_density = _mesh_density_kg_per_m3(reinforcement_specs, 'slab', slab_thickness_m)
    slab_reinforcement_kg = slab_volume * (slab_density if slab_density is not None else Decimal('90'))
    column_beam_reinforcement_kg = column_beam_volume * Decimal('90')  # link-spaced, not a mesh — flat ratio
    reinforcement_kg = slab_reinforcement_kg + column_beam_reinforcement_kg

    formwork_columns_beams = column_beam_volume * Decimal('8')
    formwork_slab_edge = perimeter * Decimal('0.15')

    member_bar_size = _member_bar_size_display(reinforcement_specs, ('column', 'beam'))
    bar_label = member_bar_size or DEFAULT_BAR_SIZE_FLAG
    bar_code = _member_bar_size_code(reinforcement_specs, ('column', 'beam')) or DEFAULT_BAR_SIZE_CODE

    reinforcement_item, reinforcement_amount = _reinforcement_line(
        f'High yield reinforcement bars ({bar_label}) to columns, beams and slab',
        reinforcement_kg, bar_code, material_for,
    )
    binding_wire_amount = _money(reinforcement_amount * BINDING_WIRE_PERCENT_OF_STEEL_COST / Decimal('100'))

    # Columns/beams and the slab always share the project's one concrete
    # grade, so they're costed as a single combined raw-material breakdown
    # rather than two separate sets of cement/sand/granite lines.
    member_desc = 'columns, beams and suspended floor slab' if framed else 'suspended floor slab'
    items = [{'description': 'Concrete Work', 'is_section_header': True}]
    items += _concrete_material_lines(
        total_concrete_volume, spec.concrete_grade, rate_for,
        context=f'{member_desc} ({spec.slab_thickness}mm), Grade {spec.get_concrete_grade_display()}',
    )
    items.append({'description': 'Reinforcement', 'is_section_header': True})
    items.append(reinforcement_item)
    items.append({
        'description': 'Binding wire (allowance, % of reinforcement cost)',
        'unit': 'sum',
        'amount': binding_wire_amount,
        'is_provisional_sum': True,
    })
    items.append({'description': 'Formwork', 'is_section_header': True})
    if framed:
        items.append({
            'description': 'Formwork to columns and beams',
            'qty': _qty(formwork_columns_beams),
            'unit': 'm²',
            'rate': rate_for('Formwork to Concrete Edges'),
        })
    items.append({
        'description': 'Formwork to slab edges',
        'qty': _qty(formwork_slab_edge),
        'unit': 'm²',
        'rate': rate_for('Formwork to Concrete Edges'),
    })
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
    items = _wall_lines(
        spec.wall_type_external, spec.get_wall_type_external_display(),
        metrics['external_wall_area'], 'external walls', rate_for,
    )
    if metrics['internal_wall_area'] > 0:
        items += _wall_lines(
            spec.wall_type_internal, spec.get_wall_type_internal_display(),
            metrics['internal_wall_area'], 'internal partitions', rate_for,
        )
    return items


def _roof_items(spec, metrics, rate_for):
    roof_area = metrics['roof_area']
    truss_material = TRUSS_MATERIAL_BY_TYPE[spec.truss_type]
    roofing_material = ROOF_MATERIAL_BY_TYPE[spec.roof_type]

    return [
        {
            'description': f'{spec.get_truss_type_display()} roof structure',
            'qty': _qty(roof_area),
            'unit': 'm²',
            'rate': rate_for(truss_material),
        },
        {
            'description': f'{spec.get_roof_type_display()} roof covering',
            'qty': _qty(roof_area),
            'unit': 'm²',
            'rate': rate_for(roofing_material),
        },
    ]


def _windows_items(metrics, rate_for):
    window_area = Decimal(metrics['window_count']) * Decimal('2.0')
    return [
        {
            'description': 'Supply and install aluminium sliding windows complete with glazing',
            'qty': _qty(window_area),
            'unit': 'm²',
            'rate': rate_for('Aluminium Sliding Window'),
        },
    ]


def _doors_items(metrics, rate_for):
    return [
        {
            'description': 'Supply and install flush doors complete with frame and ironmongery',
            'qty': Decimal(metrics['door_count']),
            'unit': 'No',
            'rate': rate_for('Flush Door with Frame and Ironmongery'),
        },
    ]


def _finishings_items(spec, metrics, rate_for):
    total_area = metrics['total_area']
    plaster_area = (metrics['external_wall_area'] + metrics['internal_wall_area']) * 2
    ceiling_material = CEILING_MATERIAL[spec.ceiling_type]
    topcoat_material = WALL_FINISH_TOPCOAT_MATERIAL.get(spec.wall_finish)

    items = [{'description': 'Floor Finishes', 'is_section_header': True}]
    if spec.floor_finish == 'tiles':
        items.append(_floor_tile_line(total_area, rate_for))
    else:
        items.append({
            'description': f'{spec.get_floor_finish_display()} to floors',
            'qty': _qty(total_area),
            'unit': 'm²',
            'rate': rate_for(FLOOR_FINISH_MATERIAL[spec.floor_finish]),
        })
    items.append({'description': 'Wall Finishes', 'is_section_header': True})
    items += _plaster_material_lines(plaster_area, rate_for)
    if topcoat_material:
        items.append({
            'description': f'{spec.get_wall_finish_display()} to walls',
            'qty': _qty(plaster_area),
            'unit': 'm²',
            'rate': rate_for(topcoat_material),
        })
    items.append({'description': 'Ceiling Finishes', 'is_section_header': True})
    items.append({
        'description': f'{spec.get_ceiling_type_display()} ceiling finish',
        'qty': _qty(total_area),
        'unit': 'm²',
        'rate': rate_for(ceiling_material),
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
        })
    if spec.water_supply in ('borehole', 'both'):
        items.append({
            'description': 'Drill and case borehole complete with submersible pump',
            'qty': Decimal('1'),
            'unit': 'No',
            'rate': rate_for('Borehole Drilling and Casing'),
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
        },
    ]


def _painting_items(spec, metrics, rate_for):
    paint_rate = rate_for('Emulsion Paint (20L bucket)')
    items = [
        {
            'description': 'Weatherproof emulsion paint, two coats, to external walls',
            'qty': _ceil_decimal(metrics['external_wall_area'] / PAINT_COVERAGE_PER_BUCKET),
            'unit': 'bucket',
            'rate': paint_rate,
        },
    ]
    if spec.wall_finish == 'paint' and metrics['internal_wall_area'] > 0:
        items.append({
            'description': 'Emulsion paint, two coats, to internal walls and ceilings',
            'qty': _ceil_decimal(metrics['internal_wall_area'] / PAINT_COVERAGE_PER_BUCKET),
            'unit': 'bucket',
            'rate': paint_rate,
        })
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
