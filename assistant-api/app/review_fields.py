"""Serbian labels and presentation only; validation stays in InspectionData."""
from app.schemas import InspectionData

LABELS = {
    'temperature_c': 'Temperatura (°C)', 'days_since_last_inspection': 'Dana od prethodnog pregleda',
    'inspection_type': 'Vrsta pregleda', 'flight_activity': 'Izletanje (0–5)', 'pollen_intake': 'Unos polena (0–3)',
    'behavior': 'Ponašanje', 'weight_class': 'Težina košnice', 'dead_bees_front': 'Mrtve pčele ispred košnice',
    'trend_flight': 'Promena izletanja', 'trend_weight': 'Promena težine', 'bee_streets': 'Ulice pčela',
    'bee_covered_frames': 'Ramovi pokriveni pčelama', 'brood_frames': 'Ramovi sa leglom',
    'open_brood': 'Otvoreno leglo', 'capped_brood': 'Zatvoreno leglo', 'brood_pattern': 'Raspored legla',
    'queen_seen': 'Matica viđena', 'eggs_seen': 'Jaja / sveže zaleženo', 'honey_frames': 'Ramovi sa medom',
    'reserves_estimate': 'Zalihe hrane', 'pollen_frames': 'Ramovi sa polenom', 'honey_bands': 'Medni venci',
    'free_space': 'Slobodan prostor', 'queen_cells': 'Matičnjaci', 'swarm_signs': 'Znaci rojenja',
    'super_added': 'Dodat nastavak', 'foundation_added': 'Dodate satne osnove', 'varroa_level': 'Varoa',
    'deformed_bees': 'Deformisane pčele', 'diarrhea': 'Proliv', 'humidity_issue': 'Problem sa vlagom',
    'beekeeper_strength': 'Jačina društva (zapažanje)', 'actions_taken': 'Preduzete radnje', 'note': 'Beleška',
}
GROUPS = {
    'Opšti podaci': ['temperature_c', 'days_since_last_inspection', 'inspection_type'],
    'Aktivnost i ponašanje': ['flight_activity', 'pollen_intake', 'behavior', 'weight_class', 'dead_bees_front', 'trend_flight', 'trend_weight', 'bee_streets', 'bee_covered_frames', 'beekeeper_strength'],
    'Matica i leglo': ['brood_pattern'],
    'Med i zalihe hrane': ['reserves_estimate', 'pollen_frames', 'honey_bands'],
    'Prostor i rojenje': ['free_space', 'queen_cells', 'swarm_signs'],
    'Zdravstvena zapažanja': ['varroa_level', 'deformed_bees', 'diarrhea', 'humidity_issue'],
    'Preduzete radnje': ['super_added', 'foundation_added', 'actions_taken'],
}
COMPACT = ['note', 'queen_seen', 'brood_frames', 'honey_frames', 'open_brood', 'capped_brood', 'eggs_seen']
FLAGS = {'open_brood', 'capped_brood', 'queen_seen', 'eggs_seen', 'swarm_signs', 'super_added', 'deformed_bees', 'diarrhea', 'humidity_issue'}


def field_spec():
    fields = {}
    for key, schema in InspectionData.model_json_schema()['properties'].items():
        spec = next(part for part in schema['anyOf'] if part['type'] != 'null')
        fields[key] = {**spec, 'label': LABELS[key], 'flag': key in FLAGS}
    return {'fields': fields, 'groups': GROUPS, 'compact': COMPACT}
