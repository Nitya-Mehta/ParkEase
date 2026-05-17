from urllib.parse import quote_plus


PARKING_LOCATIONS = {
    'Thaltej': {
        'name': 'Thaltej',
        'address': 'Thaltej, Ahmedabad, Gujarat',
        'lat': 23.0484656,
        'lng': 72.5301461,
        'pin_x': 24,
        'pin_y': 34,
    },
    'Navrangpura': {
        'name': 'Navrangpura',
        'address': 'Navrangpura, Ahmedabad, Gujarat',
        'lat': 23.0365,
        'lng': 72.5611,
        'pin_x': 48,
        'pin_y': 44,
    },
    'Paldi': {
        'name': 'Paldi',
        'address': 'Paldi, Ahmedabad, Gujarat',
        'lat': 23.0087506,
        'lng': 72.5411126,
        'pin_x': 47,
        'pin_y': 66,
    },
    'Kalupur': {
        'name': 'Kalupur',
        'address': 'Kalupur, Ahmedabad, Gujarat',
        'lat': 23.0300,
        'lng': 72.6042,
        'pin_x': 68,
        'pin_y': 49,
    },
}

AHMEDABAD_SATELLITE_MAP_URL = 'https://www.google.com/maps?q=Ahmedabad,Gujarat&z=12&t=k&output=embed'


def parking_locations_for_template(area_options):
    return [PARKING_LOCATIONS[area] for area in area_options if area in PARKING_LOCATIONS]


def google_maps_url(area):
    location = PARKING_LOCATIONS.get(area)
    if not location:
        return 'https://www.google.com/maps/search/?api=1&query=Ahmedabad'

    destination = quote_plus(f"{location['lat']},{location['lng']}")
    return f'https://www.google.com/maps/search/?api=1&query={destination}'
