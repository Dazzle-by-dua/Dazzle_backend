"""
Location-based fixed delivery charge rules for Dazzle by Dua.

Delivery Fee Policy:
- Hyderabad: ₹50
- Telangana: ₹70
- All other Indian states and union territories: ₹90

Applies to every order regardless of cart subtotal. No Google Maps or external APIs required.
"""

import re
from typing import Optional, Dict, Any, Tuple
from fastapi import HTTPException

from app.config import (
    DELIVERY_FEE_HYDERABAD,
    DELIVERY_FEE_TELANGANA,
    DELIVERY_FEE_REST_OF_INDIA
)

# Canonical 28 States and 8 Union Territories of India
INDIAN_STATES_MAP: Dict[str, str] = {
    # 28 States
    "andhra pradesh": "Andhra Pradesh",
    "ap": "Andhra Pradesh",
    "arunachal pradesh": "Arunachal Pradesh",
    "assam": "Assam",
    "bihar": "Bihar",
    "chhattisgarh": "Chhattisgarh",
    "chattisgarh": "Chhattisgarh",
    "goa": "Goa",
    "gujarat": "Gujarat",
    "haryana": "Haryana",
    "himachal pradesh": "Himachal Pradesh",
    "hp": "Himachal Pradesh",
    "jharkhand": "Jharkhand",
    "karnataka": "Karnataka",
    "kerala": "Kerala",
    "madhya pradesh": "Madhya Pradesh",
    "mp": "Madhya Pradesh",
    "maharashtra": "Maharashtra",
    "mh": "Maharashtra",
    "manipur": "Manipur",
    "meghalaya": "Meghalaya",
    "mizoram": "Mizoram",
    "nagaland": "Nagaland",
    "odisha": "Odisha",
    "orissa": "Odisha",
    "punjab": "Punjab",
    "rajasthan": "Rajasthan",
    "sikkim": "Sikkim",
    "tamil nadu": "Tamil Nadu",
    "tamilnadu": "Tamil Nadu",
    "tn": "Tamil Nadu",
    "telangana": "Telangana",
    "telengana": "Telangana",
    "ts": "Telangana",
    "tg": "Telangana",
    "tripura": "Tripura",
    "uttar pradesh": "Uttar Pradesh",
    "up": "Uttar Pradesh",
    "uttarakhand": "Uttarakhand",
    "uttaranchal": "Uttarakhand",
    "uk": "Uttarakhand",
    "west bengal": "West Bengal",
    "wb": "West Bengal",
    # 8 Union Territories
    "andaman and nicobar islands": "Andaman and Nicobar Islands",
    "andaman & nicobar islands": "Andaman and Nicobar Islands",
    "andaman and nicobar": "Andaman and Nicobar Islands",
    "andaman & nicobar": "Andaman and Nicobar Islands",
    "andaman": "Andaman and Nicobar Islands",
    "chandigarh": "Chandigarh",
    "dadra and nagar haveli and daman and diu": "Dadra and Nagar Haveli and Daman and Diu",
    "dadra & nagar haveli and daman & diu": "Dadra and Nagar Haveli and Daman and Diu",
    "dadra and nagar haveli": "Dadra and Nagar Haveli and Daman and Diu",
    "dadra & nagar haveli": "Dadra and Nagar Haveli and Daman and Diu",
    "daman and diu": "Dadra and Nagar Haveli and Daman and Diu",
    "daman & diu": "Dadra and Nagar Haveli and Daman and Diu",
    "delhi": "Delhi",
    "new delhi": "Delhi",
    "nct of delhi": "Delhi",
    "delhi ncr": "Delhi",
    "jammu and kashmir": "Jammu and Kashmir",
    "jammu & kashmir": "Jammu and Kashmir",
    "j&k": "Jammu and Kashmir",
    "j and k": "Jammu and Kashmir",
    "ladakh": "Ladakh",
    "lakshadweep": "Lakshadweep",
    "puducherry": "Puducherry",
    "pondicherry": "Puducherry",
}

# Hyderabad urban agglomeration / twin city aliases
HYDERABAD_ALIASES = {
    "hyderabad",
    "secunderabad",
    "cyberabad",
    "greater hyderabad",
    "hyd",
    "sec-bad",
    "secunderabad cantt",
}

# Known Telangana cities and districts (excluding Hyderabad)
TELANGANA_OTHER_CITIES = {
    "warangal", "hanumakonda", "hanamkonda", "kazipet",
    "karimnagar", "nizamabad", "khammam", "ramagundam",
    "mahabubnagar", "mahbubnagar", "nalgonda", "suryapet",
    "siddipet", "miryalaguda", "adilabad", "mancherial",
    "jagtial", "nirmal", "kamareddy", "kothagudem",
    "sangareddy", "medak", "wanaparthy", "gadwal",
    "nagarkurnool", "vikarabad", "bhongir", "yadadri",
    "peddapalli", "asifabad", "jangaon", "bhadradri",
    "mulugu", "narayanpet", "bellampalli", "mandamarri",
    "palwancha", "sircilla", "tandur", "bodhan", "armur"
}

# Major Indian city to state mapping for fallback parsing from freeform address
KNOWN_CITY_TO_STATE: Dict[str, str] = {
    # Telangana
    "hyderabad": "Telangana",
    "secunderabad": "Telangana",
    "cyberabad": "Telangana",
    "warangal": "Telangana",
    "hanamkonda": "Telangana",
    "hanumakonda": "Telangana",
    "karimnagar": "Telangana",
    "nizamabad": "Telangana",
    "khammam": "Telangana",
    "ramagundam": "Telangana",
    "mahabubnagar": "Telangana",
    "mahbubnagar": "Telangana",
    "nalgonda": "Telangana",
    "suryapet": "Telangana",
    "siddipet": "Telangana",
    "miryalaguda": "Telangana",
    # Maharashtra
    "mumbai": "Maharashtra",
    "bombay": "Maharashtra",
    "pune": "Maharashtra",
    "nagpur": "Maharashtra",
    "thane": "Maharashtra",
    "nashik": "Maharashtra",
    "aurangabad": "Maharashtra",
    "solapur": "Maharashtra",
    "navi mumbai": "Maharashtra",
    # Karnataka
    "bangalore": "Karnataka",
    "bengaluru": "Karnataka",
    "mysore": "Karnataka",
    "mysuru": "Karnataka",
    "mangalore": "Karnataka",
    "mangaluru": "Karnataka",
    "hubli": "Karnataka",
    "belgaum": "Karnataka",
    # Tamil Nadu
    "chennai": "Tamil Nadu",
    "madras": "Tamil Nadu",
    "coimbatore": "Tamil Nadu",
    "madurai": "Tamil Nadu",
    "salem": "Tamil Nadu",
    "trichy": "Tamil Nadu",
    "tiruchirappalli": "Tamil Nadu",
    # West Bengal
    "kolkata": "West Bengal",
    "calcutta": "West Bengal",
    "howrah": "West Bengal",
    "siliguri": "West Bengal",
    "durgapur": "West Bengal",
    # Delhi
    "delhi": "Delhi",
    "new delhi": "Delhi",
    # Gujarat
    "ahmedabad": "Gujarat",
    "surat": "Gujarat",
    "vadodara": "Gujarat",
    "rajkot": "Gujarat",
    # Rajasthan
    "jaipur": "Rajasthan",
    "jodhpur": "Rajasthan",
    "udaipur": "Rajasthan",
    "kota": "Rajasthan",
    # Uttar Pradesh
    "lucknow": "Uttar Pradesh",
    "kanpur": "Uttar Pradesh",
    "noida": "Uttar Pradesh",
    "greater noida": "Uttar Pradesh",
    "ghaziabad": "Uttar Pradesh",
    "varanasi": "Uttar Pradesh",
    "agra": "Uttar Pradesh",
    "prayagraj": "Uttar Pradesh",
    "allahabad": "Uttar Pradesh",
    # Bihar
    "patna": "Bihar",
    "gaya": "Bihar",
    # Madhya Pradesh
    "bhopal": "Madhya Pradesh",
    "indore": "Madhya Pradesh",
    "gwalior": "Madhya Pradesh",
    "jabalpur": "Madhya Pradesh",
    # Punjab / Haryana / Chandigarh
    "chandigarh": "Chandigarh",
    "ludhiana": "Punjab",
    "amritsar": "Punjab",
    "gurgaon": "Haryana",
    "gurugram": "Haryana",
    "faridabad": "Haryana",
    # Kerala
    "kochi": "Kerala",
    "cochin": "Kerala",
    "thiruvananthapuram": "Kerala",
    "trivandrum": "Kerala",
    "kozhikode": "Kerala",
    "calicut": "Kerala",
    # Andhra Pradesh
    "visakhapatnam": "Andhra Pradesh",
    "vizag": "Andhra Pradesh",
    "vijayawada": "Andhra Pradesh",
    "guntur": "Andhra Pradesh",
    "tirupati": "Andhra Pradesh",
    "nellore": "Andhra Pradesh",
    # Odisha
    "bhubaneswar": "Odisha",
    "cuttack": "Odisha",
    # Assam
    "guwahati": "Assam",
    # Jharkhand
    "ranchi": "Jharkhand",
    "jamshedpur": "Jharkhand",
    # Chhattisgarh
    "raipur": "Chhattisgarh",
    # Uttarakhand
    "dehradun": "Uttarakhand",
    # Himachal Pradesh
    "shimla": "Himachal Pradesh",
    # Jammu & Kashmir
    "srinagar": "Jammu and Kashmir",
    "jammu": "Jammu and Kashmir",
    # Goa
    "panaji": "Goa",
    "margao": "Goa"
}

# Foreign countries indicators to explicitly reject
FOREIGN_COUNTRIES = {
    "usa", "united states", "america", "uk", "united kingdom", "great britain",
    "canada", "australia", "germany", "france", "uae", "united arab emirates",
    "dubai", "pakistan", "bangladesh", "sri lanka", "nepal", "bhutan", "china",
    "singapore", "malaysia", "saudi arabia", "qatar", "kuwait", "oman"
}


def _clean_str(val: Optional[str]) -> str:
    if not val:
        return ""
    # Strip whitespace and convert to clean lowercase
    return re.sub(r"\s+", " ", str(val).strip().lower())


def _extract_location_from_address(address: str) -> Tuple[Optional[str], Optional[str]]:
    """Attempt to parse recognized Indian city and state from an address string."""
    addr_clean = _clean_str(address)
    if not addr_clean:
        return None, None

    # Check for recognized states in address
    matched_state = None
    for alias, canon in INDIAN_STATES_MAP.items():
        # Match as distinct word or phrase
        pattern = r"\b" + re.escape(alias) + r"\b"
        if re.search(pattern, addr_clean):
            matched_state = canon
            break

    # Check for recognized cities in address
    matched_city = None
    for city_key, state_name in KNOWN_CITY_TO_STATE.items():
        pattern = r"\b" + re.escape(city_key) + r"\b"
        if re.search(pattern, addr_clean):
            matched_city = city_key.title()
            if not matched_state:
                matched_state = state_name
            break

    return matched_city, matched_state


def calculate_delivery_charge(
    city: Optional[str] = None,
    state: Optional[str] = None,
    address: Optional[str] = None
) -> Dict[str, Any]:
    """
    Independently validate delivery location and calculate the fixed delivery charge.
    
    Rules:
    - Hyderabad: ₹50.0
    - Telangana: ₹70.0
    - All other Indian states and union territories: ₹90.0
    
    Raises HTTPException(status_code=400) if location is ambiguous, missing, or outside India.
    """
    clean_city = _clean_str(city)
    clean_state = _clean_str(state)
    clean_addr = _clean_str(address)

    # 1. Foreign country / international check
    full_text = f"{clean_city} {clean_state} {clean_addr}"
    words = set(re.findall(r"\b[a-z\s]+\b", full_text))
    for fc in FOREIGN_COUNTRIES:
        if re.search(r"\b" + re.escape(fc) + r"\b", full_text):
            if "india" not in full_text:
                raise HTTPException(
                    status_code=400,
                    detail=f"We currently only deliver within India. Location referencing '{fc.title()}' is not supported."
                )

    # 2. Extract city/state if missing from freeform address
    if not clean_city or not clean_state:
        extracted_city, extracted_state = _extract_location_from_address(clean_addr)
        if not clean_city and extracted_city:
            clean_city = _clean_str(extracted_city)
        if not clean_state and extracted_state:
            clean_state = _clean_str(extracted_state)

    # 3. If city was provided as Hyderabad / Secunderabad and state was omitted or ambiguous
    if clean_city in HYDERABAD_ALIASES:
        canonical_state = "Telangana"
        return {
            "delivery_fee": DELIVERY_FEE_HYDERABAD,
            "rate_type": "hyderabad",
            "city": "Hyderabad",
            "state": canonical_state,
            "description": f"Hyderabad (₹{int(DELIVERY_FEE_HYDERABAD)})"
        }

    # 4. Resolve State against recognized Indian States & UTs
    canonical_state = None
    if clean_state:
        # Direct lookup or alias
        canonical_state = INDIAN_STATES_MAP.get(clean_state)
        if not canonical_state:
            # Try partial substring match on state
            for alias, canon in INDIAN_STATES_MAP.items():
                if alias in clean_state or clean_state in alias:
                    canonical_state = canon
                    break

    # If state still unknown, check if city is a known Indian city
    if not canonical_state and clean_city:
        canonical_state = KNOWN_CITY_TO_STATE.get(clean_city)

    # If state cannot be resolved or is invalid
    if not canonical_state:
        if clean_state:
            raise HTTPException(
                status_code=400,
                detail=f"'{state}' is not a recognized Indian state or union territory. Please provide a valid Indian delivery state."
            )
        raise HTTPException(
            status_code=400,
            detail="Delivery address must include a valid Indian state and city to calculate delivery charges."
        )

    # 5. Handle Telangana (Hyderabad vs Telangana)
    if canonical_state == "Telangana":
        # Check if city is Hyderabad or twin cities
        if clean_city in HYDERABAD_ALIASES:
            return {
                "delivery_fee": DELIVERY_FEE_HYDERABAD,
                "rate_type": "hyderabad",
                "city": "Hyderabad",
                "state": canonical_state,
                "description": f"Hyderabad (₹{int(DELIVERY_FEE_HYDERABAD)})"
            }
        
        # In Telangana, city is required to differentiate Hyderabad (₹50) from Telangana (₹70)
        if not clean_city:
            raise HTTPException(
                status_code=400,
                detail="City name is required to determine delivery charges within Telangana (Hyderabad: ₹50, Telangana: ₹70)."
            )

        resolved_city_name = city.strip().title() if city else clean_city.title()
        return {
            "delivery_fee": DELIVERY_FEE_TELANGANA,
            "rate_type": "telangana",
            "city": resolved_city_name,
            "state": canonical_state,
            "description": f"Telangana (₹{int(DELIVERY_FEE_TELANGANA)})"
        }

    # 6. All other Indian States and Union Territories (₹90)
    resolved_city_name = city.strip().title() if city else (clean_city.title() if clean_city else canonical_state)
    return {
        "delivery_fee": DELIVERY_FEE_REST_OF_INDIA,
        "rate_type": "rest_of_india",
        "city": resolved_city_name,
        "state": canonical_state,
        "description": f"{canonical_state} (₹{int(DELIVERY_FEE_REST_OF_INDIA)})"
    }
