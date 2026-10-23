"""Country/region extraction from affiliation strings.

WoS and Scopus addresses end with a country, often abbreviated (``USA``,
``PEOPLES R CHINA``). The matcher only accepts a known country at the END of an
address, so a state or a city is never promoted to a country by guesswork.
"""

import re

#: ISO 3166 short names plus the spellings the major exports actually emit.
_COUNTRIES = """
Afghanistan
Albania
Algeria
American Samoa
Andorra
Angola
Anguilla
Antarctica
Antigua and Barbuda
Argentina
Armenia
Aruba
Australia
Austria
Azerbaijan
Bahamas
Bahrain
Bangladesh
Barbados
Belarus
Belgium
Belize
Benin
Bermuda
Bhutan
Bolivia
Bonaire
Bosnia and Herzegovina
Botswana
Bouvet Island
Brazil
British Indian Ocean Territory
Brunei
Bulgaria
Burkina Faso
Burundi
Cambodia
Cameroon
Canada
Cape Verde
Cayman Islands
Central African Republic
Chad
Chile
China
Christmas Island
Cocos Islands
Colombia
Comoros
Congo
Cook Islands
Costa Rica
Croatia
Cuba
Curacao
Cyprus
Czech Republic
Czechia
Denmark
Djibouti
Dominica
Dominican Republic
Ecuador
Egypt
El Salvador
Equatorial Guinea
Eritrea
Estonia
Eswatini
Ethiopia
Falkland Islands
Faroe Islands
Fiji
Finland
France
French Guiana
French Polynesia
French Southern Territories
Gabon
Gambia
Georgia
Germany
Ghana
Gibraltar
Greece
Greenland
Grenada
Guadeloupe
Guam
Guatemala
Guernsey
Guinea
Guinea-Bissau
Guyana
Haiti
Heard Island and McDonald Islands
Holy See
Honduras
Hong Kong
Hungary
Iceland
India
Indonesia
Iran
Iraq
Ireland
Isle of Man
Israel
Italy
Ivory Coast
Jamaica
Japan
Jersey
Jordan
Kazakhstan
Kenya
Kiribati
Kosovo
Kuwait
Kyrgyzstan
Laos
Latvia
Lebanon
Lesotho
Liberia
Libya
Liechtenstein
Lithuania
Luxembourg
Macau
Madagascar
Malawi
Malaysia
Maldives
Mali
Malta
Marshall Islands
Martinique
Mauritania
Mauritius
Mayotte
Mexico
Micronesia
Moldova
Monaco
Mongolia
Montenegro
Montserrat
Morocco
Mozambique
Myanmar
Namibia
Nauru
Nepal
Netherlands
New Caledonia
New Zealand
Nicaragua
Niger
Nigeria
Niue
Norfolk Island
North Korea
North Macedonia
Northern Mariana Islands
Norway
Oman
Pakistan
Palau
Palestine
Panama
Papua New Guinea
Paraguay
Peru
Philippines
Pitcairn
Poland
Portugal
Puerto Rico
Qatar
Reunion
Romania
Russia
Rwanda
Saint Barthelemy
Saint Helena
Saint Kitts and Nevis
Saint Lucia
Saint Martin
Saint Pierre and Miquelon
Saint Vincent and the Grenadines
Samoa
San Marino
Sao Tome and Principe
Saudi Arabia
Senegal
Serbia
Seychelles
Sierra Leone
Singapore
Sint Maarten
Slovakia
Slovenia
Solomon Islands
Somalia
South Africa
South Georgia and the South Sandwich Islands
South Korea
South Sudan
Spain
Sri Lanka
Sudan
Suriname
Svalbard and Jan Mayen
Sweden
Switzerland
Syria
Taiwan
Tajikistan
Tanzania
Thailand
Timor-Leste
Togo
Tokelau
Tonga
Trinidad and Tobago
Tunisia
Turkey
Turkmenistan
Turks and Caicos Islands
Tuvalu
Uganda
Ukraine
United Arab Emirates
United Kingdom
United States
United States Minor Outlying Islands
Uruguay
Uzbekistan
Vanuatu
Venezuela
Vietnam
Virgin Islands
Wallis and Futuna
Western Sahara
Yemen
Zambia
Zimbabwe
England
Scotland
Wales
Northern Ireland
"""

_ALIASES = {
    'USA': 'United States',
    'U S A': 'United States',
    'US': 'United States',
    'UNITED STATES OF AMERICA': 'United States',
    'PEOPLES R CHINA': "People's Republic of China",
    "PEOPLE'S REPUBLIC OF CHINA": "People's Republic of China",
    'P R CHINA': "People's Republic of China",
    'PR CHINA': "People's Republic of China",
    'CHINA MAINLAND': 'China',
    'MAINLAND CHINA': 'China',
    'REPUBLIC OF KOREA': 'South Korea',
    'KOREA': 'South Korea',
    'S KOREA': 'South Korea',
    'DEMOCRATIC PEOPLES REPUBLIC OF KOREA': 'North Korea',
    'RUSSIA': 'Russia',
    'RUSSIAN FEDERATION': 'Russia',
    'IRAN': 'Iran',
    'ISLAMIC REPUBLIC OF IRAN': 'Iran',
    'VIET NAM': 'Vietnam',
    'CZECH REP': 'Czech Republic',
    'UNITED KINGDOM': 'United Kingdom',
    'UK': 'United Kingdom',
    'GREAT BRITAIN': 'United Kingdom',
    'ENGLAND': 'England',
    'SCOTLAND': 'Scotland',
    'WALES': 'Wales',
    'NORTH IRELAND': 'Northern Ireland',
    'NORTHERN IRELAND': 'Northern Ireland',
    'U ARAB EMIRATES': 'United Arab Emirates',
    'UNITED ARAB EMIRATES': 'United Arab Emirates',
    'SAUDI ARABIA': 'Saudi Arabia',
    'SOUTH AFRICA': 'South Africa',
    'NEW ZEALAND': 'New Zealand',
    'THE NETHERLANDS': 'Netherlands',
}

_ALIASES = {**_ALIASES, **{name.upper(): name for name in _COUNTRIES.splitlines() if name.strip()}}
_ALIASES = {alias: canonical for alias, canonical in _ALIASES.items() if alias}
_ORDERED = sorted(_ALIASES, key=len, reverse=True)
_TRAILING = re.compile(r'[^A-Z ]+$')


def country_in_affiliation(value: str) -> str:
    """The canonical country ending this address, or ``''`` when none is known."""
    text = re.sub(r'\s+', ' ', str(value or '')).strip()
    if not text:
        return ''
    # Drop e-mail addresses, postcodes and a trailing period before matching.
    text = re.sub(r'\S+@\S+', ' ', text)
    upper = re.sub(r'[^A-Z&., ]', ' ', text.upper())
    upper = re.sub(r'\s+', ' ', upper).strip(' .,')
    if not upper:
        return ''
    for alias in _ORDERED:
        if len(alias) < 2:
            continue
        if upper == alias or upper.endswith(' ' + alias) or upper.endswith(',' + alias):
            return _ALIASES[alias]
    return ''


def countries_in(text: str) -> list[str]:
    """Every distinct country found in a semicolon/newline separated address list."""
    found: list[str] = []
    for part in re.split(r'[;\n]+', str(text or '')):
        country = country_in_affiliation(part)
        if country and country not in found:
            found.append(country)
    return found
