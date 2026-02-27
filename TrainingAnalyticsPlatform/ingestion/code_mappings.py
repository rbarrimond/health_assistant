"""FIT protocol manufacturer and product code mappings.

This module provides bidirectional mappings between FIT protocol numeric codes
and their string names for manufacturers and products. These are extracted from
the official FIT SDK profile (fitdecode library).

Also provides mappings for Apple Watch internal device identifiers (e.g., "Watch7,12")
that appear in FIT file_id.product_name fields, enabling lookup of marketing names.

References:
- fitdecode: https://github.com/polyvertex/fitdecode
- FIT SDK: https://developer.garmin.com/fit/overview/
- Apple device internal IDs: https://gist.github.com/adamawolf/3048717
"""

# FIT Manufacturer Codes (manufacturer field in file_id message)
# Reference: fitdecode profile.py - 'manufacturer' FieldType
MANUFACTURER_CODES = {
    1: "garmin",
    2: "garmin_fr405_antfs",  # Do not use. Used by FR405 for ANTFS man id.
    3: "zephyr",
    4: "dayton",
    5: "idt",
    6: "srm",
    7: "quarq",
    8: "ibike",
    9: "saris",
    10: "spark_hk",
    11: "tanita",
    12: "echowell",
    13: "dynastream_oem",
    14: "nautilus",
    15: "dynastream",
    16: "timex",
    17: "metrigear",
    18: "xelic",
    19: "beurer",
    20: "cardiosport",
    21: "a_and_d",
    22: "hmm",
    23: "suunto",
    24: "thita_elektronik",
    25: "gpulse",
    26: "clean_mobile",
    27: "pedal_brain",
    28: "peaksware",
    29: "saxonar",
    30: "lemond_fitness",
    31: "dexcom",
    32: "wahoo_fitness",
    33: "octane_fitness",
    34: "archinoetics",
    35: "the_hurt_box",
    36: "citizen_systems",
    37: "magellan",
    38: "osynce",
    39: "holux",
    40: "concept2",
    41: "shimano",
    42: "one_giant_leap",
    43: "ace_sensor",
    44: "brim_brothers",
    45: "xplova",
    46: "perception_digital",
    47: "bf1systems",
    48: "pioneer",
    49: "spantec",
    50: "metalogics",
    51: "4iiiis",
    52: "seiko_epson",
    53: "seiko_epson_oem",
    54: "ifor_powell",
    55: "maxwell_guider",
    56: "star_trac",
    57: "breakaway",
    58: "alatech_technology_ltd",
    59: "mio_technology_europe",
    60: "rotor",
    61: "geonaute",
    62: "id_bike",
    63: "specialized",
    64: "wtek",
    65: "physical_enterprises",
    66: "north_pole_engineering",
    67: "bkool",
    68: "cateye",
    69: "stages_cycling",
    70: "sigmasport",
    71: "tomtom",
    72: "peripedal",
    73: "wattbike",
    76: "moxy",
    77: "ciclosport",
    78: "powerbahn",
    79: "acorn_projects_aps",
    80: "lifebeam",
    81: "bontrager",
    82: "wellgo",
    83: "scosche",
    84: "magura",
    85: "woodway",
    86: "elite",
    87: "nielsen_kellerman",
    88: "dk_city",
    89: "tacx",
    90: "direction_technology",
    91: "magtonic",
    92: "1partcarbon",
    93: "inside_ride_technologies",
    94: "sound_of_motion",
    95: "stryd",
    96: "icg",  # Indoorcycling Group
    97: "MiPulse",
    98: "bsx_athletics",
    99: "look",
    100: "campagnolo_srl",
    101: "body_bike_smart",
    102: "praxisworks",
    103: "limits_technology",  # Limits Technology Ltd.
    104: "topaction_technology",  # TopAction Technology Inc.
    105: "cosinuss",
    106: "fitcare",
    107: "magene",
    108: "giant_manufacturing_co",
    109: "tigrasport",  # Tigrasport
    110: "salutron",
    111: "technogym",
    112: "bryton_sensors",
    113: "latitude_limited",
    114: "soaring_technology",
    115: "igpsport",
    116: "thinkrider",
    117: "gopher_sport",
    118: "waterrower",
    119: "orangetheory",
    120: "inpeak",
    121: "kinetic",
    122: "johnson_health_tech",
    123: "polar_electro",
    124: "seesense",
    125: "nci_technology",
    126: "iqsquare",
    127: "leomo",
    128: "ifit_com",
    129: "coros_byte",
    130: "versa_design",
    131: "chileaf",
    132: "cycplus",
    133: "gravaa_byte",
    134: "sigeyi",
    135: "coospo",
    136: "geoid",
    137: "bosch",
    138: "kyto",
    139: "kinetic_sports",
    140: "decathlon_byte",
    141: "tq_systems",
    142: "tag_heuer",
    143: "keiser_fitness",
    144: "zwift_byte",
    145: "porsche_ep",
    146: "blackbird",
    147: "meilan_byte",
    148: "ezon",
    149: "laisi",
    150: "myzone",
    151: "abawo",
    152: "bafang",
    153: "luhong_technology",
    255: "development",  # Apple uses this (no official Apple manufacturer code)
    257: "healthandlife",
    258: "lezyne",
    259: "scribe_labs",
    260: "zwift",
    261: "watteam",
    262: "recon",
    263: "favero_electronics",
    264: "dynovelo",
    265: "strava",
    266: "precor",  # Amer Sports
    267: "bryton",
    268: "sram",
    269: "navman",  # MiTAC Global Corporation (Mio Technology)
    270: "cobi",  # COBI GmbH
    271: "spivi",
    272: "mio_magellan",
    273: "evesports",
    274: "sensitivus_gauge",
    275: "podoon",
    276: "life_time_fitness",
    277: "falco_e_motors",  # Falco eMotors Inc.
    278: "minoura",
    279: "cycliq",
    280: "luxottica",
    281: "trainer_road",
    282: "the_sufferfest",
    283: "fullspeedahead",
    284: "virtualtraining",
    285: "feedbacksports",
    286: "omata",
    287: "vdo",
    288: "magneticdays",
    289: "hammerhead",
    290: "kinetic_by_kurt",
    291: "shapelog",
    292: "dabuziduo",
    293: "jetblack",
    294: "coros",
    295: "virtugo",
    296: "velosense",
    297: "cycligentinc",
    298: "trailforks",
    299: "mahle_ebikemotion",
    300: "nurvv",
    301: "microprogram",
    302: "zone5cloud",
    303: "greenteg",
    304: "yamaha_motors",
    305: "whoop",
    306: "gravaa",
    307: "onelap",
    308: "monark_exercise",
    309: "form",
    310: "decathlon",
    311: "syncros",
    312: "heatup",
    313: "cannondale",
    314: "true_fitness",
    315: "RGT_cycling",
    316: "vasa",
    317: "race_republic",
    318: "fazua",
    319: "oreka_training",
    320: "lsec",  # Lishun Electric & Communication
    321: "lululemon_studio",
    322: "shanyue",
    323: "spinning_mda",
    324: "hilldating",
    325: "aero_sensor",
    326: "nike",
    327: "magicshine",
    328: "ictrainer",
    329: "absolute_cycling",
    330: "eo_swimbetter",
    331: "mywhoosh",
    332: "ravemen",
    333: "tektro_racing_products",
    334: "darad_innovation_corporation",
    335: "cycloptim",
    5759: "actigraphcorp",
}

# Reverse mapping: manufacturer name to code
MANUFACTURER_NAME_TO_CODE = {v: k for k, v in MANUFACTURER_CODES.items()}

# Garmin API ingestion allowlist (manufacturer codes).
GARMIN_API_ALLOWED_MANUFACTURERS = {1, 260}

# Garmin Product Codes (subset of codes)
# Reference: fitdecode profile.py - 'garmin_product' FieldType
GARMIN_PRODUCT_CODES = {
    1: "hrm1",
    2: "axh01",  # AXH01 HRM chipset
    3: "axb01",
    4: "axb02",
    5: "hrm2ss",
    6: "dsi_alf02",
    7: "hrm3ss",
    8: "hrm_run_single_byte_product_id",  # hrm_run model for HRM ANT+ messaging
    9: "bsm",  # BSM model for ANT+ messaging
    10: "bcm",  # BCM model for ANT+ messaging
    11: "axs01",  # AXS01 HRM Bike Chipset model for ANT+ messaging
    12: "hrm_tri_single_byte_product_id",  # hrm_tri model for HRM ANT+ messaging
    13: "hrm4_run_single_byte_product_id",  # hrm4 run model for HRM ANT+ messaging
    14: "fr225_single_byte_product_id",  # fr225 model for HRM ANT+ messaging
    15: "gen3_bsm_single_byte_product_id",  # gen3_bsm for Bike Speed ANT+
    16: "gen3_bcm_single_byte_product_id",  # gen3_bcm for Bike Cadence ANT+
    22: "hrm_fit_single_byte_product_id",
    255: "OHR",  # Garmin Wearable Optical Heart Rate Sensor for ANT+ HR
    # Add more Garmin products as needed - truncated for brevity, full list available in fitdecode
}

# Favero Electronics Product Codes
# Reference: fitdecode profile.py - 'favero_product' FieldType
FAVERO_PRODUCT_CODES = {
    10: "assioma_uno",
    12: "assioma_duo",
}

# Apple Product Codes (manufacturer_id = 255 "development")
# Reference: Manually curated - not from FIT SDK (Apple has no official product enum)
# NOTE: These are marketing names. Actual FIT file_id.product_name contains Apple internal
# product identifiers (e.g., "Watch 7,12" for Apple Watch Ultra 3, "iPhone16,2" for iPhone 15 Pro).
# Device classification uses string matching on device_name, not product code validation.
APPLE_PRODUCT_CODES = {
    # iPhone models
    1: "iPhone",
    2: "iPhone 3G",
    3: "iPhone 3GS",
    4: "iPhone 4",
    5: "iPhone 4S",
    6: "iPhone 5",
    7: "iPhone 5C",
    8: "iPhone 5S",
    9: "iPhone 6",
    10: "iPhone 6 Plus",
    11: "iPhone 6S",
    12: "iPhone 6S Plus",
    13: "iPhone SE",
    14: "iPhone 7",
    15: "iPhone 7 Plus",
    16: "iPhone 8",
    17: "iPhone 8 Plus",
    18: "iPhone X",
    19: "iPhone XS",
    20: "iPhone XS Max",
    21: "iPhone XR",
    22: "iPhone 11",
    23: "iPhone 11 Pro",
    24: "iPhone 11 Pro Max",
    25: "iPhone SE (2nd gen)",
    26: "iPhone 12 mini",
    27: "iPhone 12",
    28: "iPhone 12 Pro",
    29: "iPhone 12 Pro Max",
    30: "iPhone 13 mini",
    31: "iPhone 13",
    32: "iPhone 13 Pro",
    33: "iPhone 13 Pro Max",
    34: "iPhone SE (3rd gen)",
    35: "iPhone 14",
    36: "iPhone 14 Plus",
    37: "iPhone 14 Pro",
    38: "iPhone 14 Pro Max",
    39: "iPhone 15",
    40: "iPhone 15 Plus",
    41: "iPhone 15 Pro",
    42: "iPhone 15 Pro Max",
    # Apple Watch models
    200: "Apple Watch (1st gen) 38mm",
    201: "Apple Watch (1st gen) 42mm",
    202: "Apple Watch Series 1 38mm",
    203: "Apple Watch Series 1 42mm",
    204: "Apple Watch Series 2 38mm",
    205: "Apple Watch Series 2 42mm",
    206: "Apple Watch Series 3 38mm (GPS)",
    207: "Apple Watch Series 3 42mm (GPS)",
    208: "Apple Watch Series 3 38mm (GPS+Cellular)",
    209: "Apple Watch Series 3 42mm (GPS+Cellular)",
    210: "Apple Watch Series 4 40mm (GPS)",
    211: "Apple Watch Series 4 44mm (GPS)",
    212: "Apple Watch Series 4 40mm (GPS+Cellular)",
    213: "Apple Watch Series 4 44mm (GPS+Cellular)",
    214: "Apple Watch Series 5 40mm (GPS)",
    215: "Apple Watch Series 5 44mm (GPS)",
    216: "Apple Watch Series 5 40mm (GPS+Cellular)",
    217: "Apple Watch Series 5 44mm (GPS+Cellular)",
    218: "Apple Watch SE 40mm (GPS)",
    219: "Apple Watch SE 44mm (GPS)",
    220: "Apple Watch SE 40mm (GPS+Cellular)",
    221: "Apple Watch SE 44mm (GPS+Cellular)",
    222: "Apple Watch Series 6 40mm (GPS)",
    223: "Apple Watch Series 6 44mm (GPS)",
    224: "Apple Watch Series 6 40mm (GPS+Cellular)",
    225: "Apple Watch Series 6 44mm (GPS+Cellular)",
    226: "Apple Watch Series 7 41mm (GPS)",
    227: "Apple Watch Series 7 45mm (GPS)",
    228: "Apple Watch Series 7 41mm (GPS+Cellular)",
    229: "Apple Watch Series 7 45mm (GPS+Cellular)",
    230: "Apple Watch SE (2nd gen) 40mm (GPS)",
    231: "Apple Watch SE (2nd gen) 44mm (GPS)",
    232: "Apple Watch SE (2nd gen) 40mm (GPS+Cellular)",
    233: "Apple Watch SE (2nd gen) 44mm (GPS+Cellular)",
    234: "Apple Watch Series 8 41mm (GPS)",
    235: "Apple Watch Series 8 45mm (GPS)",
    236: "Apple Watch Series 8 41mm (GPS+Cellular)",
    237: "Apple Watch Series 8 45mm (GPS+Cellular)",
    238: "Apple Watch Ultra 49mm (GPS+Cellular)",
    239: "Apple Watch Series 9 41mm (GPS)",
    240: "Apple Watch Series 9 45mm (GPS)",
    241: "Apple Watch Series 9 41mm (GPS+Cellular)",
    242: "Apple Watch Series 9 45mm (GPS+Cellular)",
    243: "Apple Watch Ultra 2 49mm (GPS+Cellular)",
    244: "Apple Watch Series 10 42mm (GPS)",
    245: "Apple Watch Series 10 46mm (GPS)",
    246: "Apple Watch Series 10 42mm (GPS+Cellular)",
    247: "Apple Watch Series 10 46mm (GPS+Cellular)",
    248: "Apple Watch SE (3rd gen) 40mm (GPS)",
    249: "Apple Watch SE (3rd gen) 44mm (GPS)",
    250: "Apple Watch SE (3rd gen) 40mm (GPS+Cellular)",
    251: "Apple Watch SE (3rd gen) 44mm (GPS+Cellular)",
    252: "Apple Watch Series 11 42mm (GPS)",
    253: "Apple Watch Series 11 46mm (GPS)",
    254: "Apple Watch Series 11 42mm (GPS+Cellular)",
    255: "Apple Watch Series 11 46mm (GPS+Cellular)",
    256: "Apple Watch Ultra 3 49mm (GPS+Cellular)",
}

# Apple Watch Internal Product Identifiers
# These are the actual device identifier strings that appear in FIT file_id.product_name
# Reference: https://gist.github.com/adamawolf/3048717 and https://www.theiphonewiki.com/wiki/Models
APPLE_WATCH_INTERNAL_IDS = {
    # Series 0 (original Apple Watch)
    "Watch1,1": "Apple Watch (1st gen) 38mm",
    "Watch1,2": "Apple Watch (1st gen) 42mm",
    
    # Series 1
    "Watch2,6": "Apple Watch Series 1 38mm",
    "Watch2,7": "Apple Watch Series 1 42mm",
    
    # Series 2
    "Watch2,3": "Apple Watch Series 2 38mm GPS+Cellular",
    "Watch2,4": "Apple Watch Series 2 42mm GPS+Cellular",
    
    # Series 3
    "Watch3,1": "Apple Watch Series 3 38mm GPS+Cellular",
    "Watch3,2": "Apple Watch Series 3 42mm GPS+Cellular",
    "Watch3,3": "Apple Watch Series 3 38mm GPS",
    "Watch3,4": "Apple Watch Series 3 42mm GPS",
    
    # Series 4
    "Watch4,1": "Apple Watch Series 4 40mm GPS",
    "Watch4,2": "Apple Watch Series 4 44mm GPS",
    "Watch4,3": "Apple Watch Series 4 40mm GPS+Cellular",
    "Watch4,4": "Apple Watch Series 4 44mm GPS+Cellular",
    
    # Series 5
    "Watch5,1": "Apple Watch Series 5 40mm GPS",
    "Watch5,2": "Apple Watch Series 5 44mm GPS",
    "Watch5,3": "Apple Watch Series 5 40mm GPS+Cellular",
    "Watch5,4": "Apple Watch Series 5 44mm GPS+Cellular",
    
    # SE (1st gen)
    "Watch5,9": "Apple Watch SE 40mm GPS",
    "Watch5,10": "Apple Watch SE 44mm GPS",
    "Watch5,11": "Apple Watch SE 40mm GPS+Cellular",
    "Watch5,12": "Apple Watch SE 44mm GPS+Cellular",
    
    # Series 6
    "Watch6,1": "Apple Watch Series 6 40mm GPS",
    "Watch6,2": "Apple Watch Series 6 44mm GPS",
    "Watch6,3": "Apple Watch Series 6 40mm GPS+Cellular",
    "Watch6,4": "Apple Watch Series 6 44mm GPS+Cellular",
    
    # Series 7
    "Watch6,6": "Apple Watch Series 7 41mm GPS",
    "Watch6,7": "Apple Watch Series 7 45mm GPS",
    "Watch6,8": "Apple Watch Series 7 41mm GPS+Cellular",
    "Watch6,9": "Apple Watch Series 7 45mm GPS+Cellular",
    
    # SE (2nd gen)
    "Watch6,10": "Apple Watch SE (2nd gen) 40mm GPS",
    "Watch6,11": "Apple Watch SE (2nd gen) 44mm GPS",
    "Watch6,12": "Apple Watch SE (2nd gen) 40mm GPS+Cellular",
    "Watch6,13": "Apple Watch SE (2nd gen) 44mm GPS+Cellular",
    
    # Series 8
    "Watch6,14": "Apple Watch Series 8 41mm GPS",
    "Watch6,15": "Apple Watch Series 8 45mm GPS",
    "Watch6,16": "Apple Watch Series 8 41mm GPS+Cellular",
    "Watch6,17": "Apple Watch Series 8 45mm GPS+Cellular",
    
    # Ultra (1st gen)
    "Watch6,18": "Apple Watch Ultra 49mm",
    
    # Series 9
    "Watch7,1": "Apple Watch Series 9 41mm GPS",
    "Watch7,2": "Apple Watch Series 9 45mm GPS",
    "Watch7,3": "Apple Watch Series 9 41mm GPS+Cellular",
    "Watch7,4": "Apple Watch Series 9 45mm GPS+Cellular",
    
    # Ultra 2
    "Watch7,5": "Apple Watch Ultra 2 49mm",
    
    # Series 10
    "Watch7,8": "Apple Watch Series 10 42mm GPS",
    "Watch7,9": "Apple Watch Series 10 46mm GPS",
    "Watch7,10": "Apple Watch Series 10 42mm GPS+Cellular",
    "Watch7,11": "Apple Watch Series 10 46mm GPS+Cellular",
    
    # Ultra 3
    "Watch7,12": "Apple Watch Ultra 3 49mm",
    
    # SE (3rd gen)
    "Watch7,13": "Apple Watch SE (3rd gen) 40mm GPS",
    "Watch7,14": "Apple Watch SE (3rd gen) 44mm GPS",
    "Watch7,15": "Apple Watch SE (3rd gen) 40mm GPS+Cellular",
    "Watch7,16": "Apple Watch SE (3rd gen) 44mm GPS+Cellular",
    
    # Series 11
    "Watch7,17": "Apple Watch Series 11 42mm GPS",
    "Watch7,18": "Apple Watch Series 11 46mm GPS",
    "Watch7,19": "Apple Watch Series 11 42mm GPS+Cellular",
    "Watch7,20": "Apple Watch Series 11 46mm GPS+Cellular",
}


def get_manufacturer_name(code: int) -> str:
    """Get manufacturer name from FIT code.
    
    Args:
        code: FIT manufacturer code (uint16)
        
    Returns:
        Manufacturer name or the code as string if not found
    """
    return MANUFACTURER_CODES.get(code, f"unknown_{code}")


def get_manufacturer_code(name: str) -> int:
    """Get FIT manufacturer code from name.
    
    Args:
        name: Manufacturer name
        
    Returns:
        FIT manufacturer code or 255 (development) if not found
    """
    return MANUFACTURER_NAME_TO_CODE.get(name.lower(), 255)


def get_garmin_product_name(code: int) -> str:
    """Get Garmin product name from FIT code.
    
    Args:
        code: Garmin product code (uint16)
        
    Returns:
        Product name or the code as string if not found
    """
    return GARMIN_PRODUCT_CODES.get(code, f"garmin_{code}")


def get_favero_product_name(code: int) -> str:
    """Get Favero product name from FIT code.
    
    Args:
        code: Favero product code (uint16)
        
    Returns:
        Product name or the code as string if not found
    """
    return FAVERO_PRODUCT_CODES.get(code, f"favero_{code}")


def get_apple_product_name(code: int) -> str:
    """Get Apple product name from FIT code.
    
    Args:
        code: Apple product code (uint16)
        
    Returns:
        Product name or the code as string if not found
    """
    return APPLE_PRODUCT_CODES.get(code, f"apple_{code}")


def get_apple_watch_model(internal_id: str) -> str:
    """Get Apple Watch marketing name from internal identifier.
    
    Internal identifiers are the actual strings that appear in FIT file_id.product_name
    fields, such as "Watch7,12" for Apple Watch Ultra 3.
    
    Args:
        internal_id: Apple Watch internal identifier (e.g., "Watch7,12")
        
    Returns:
        Marketing name or the internal_id as-is if not found
        
    Examples:
        >>> get_apple_watch_model("Watch7,12")
        'Apple Watch Ultra 3 49mm'
        >>> get_apple_watch_model("Watch6,18")
        'Apple Watch Ultra 49mm'
    """
    return APPLE_WATCH_INTERNAL_IDS.get(internal_id, internal_id)
