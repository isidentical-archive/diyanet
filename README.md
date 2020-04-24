# Diyanet

Python interface for internal API of Turkey's Presidency of Religious
Affairs to get prayer times.

## API
### Units
- `GeographicUnit`, base class for all geographic units. All units share these members
    * `idx`: `int` => Internal ID (to use in API)
    * `name`: `str` => Name of the country
- `Country`, unit for countries
- `State`, unit for states (if no states present in given country, this will be same with `Country`)
    * `country`: `Country` => A link to it's country
- `Region`, unit for citites/regions
    * `url`: `str` => URL that points out to prayer times page for that specific region
    * `state`: `State` => A link to it's state
    * `country`: `Country` => A link to it's country
- `PrayerTimes`, unit for prayer times of a day
    * `fajr`: `time`
    * `sunrise`: `time`
    * `dhuhr`: `time`
    * `asr`: `time`
    * `maghrib`: `time`
    * `isha`: `time`

### API
All methods described below are members of `Diyanet` class
- `get_countries`: `() -> Iterator[Country]` => Iterates through all available countries
- `get_states`: `(country: Country) -> Iterator[State]` => Iterates through all available states
- `get_regions`: `(state: State) -> Iterator[Region]` => Iterates through all available regions
- `get_country` / `get_state`/ `get_region` => Takes a `name` (and depending on the context, a geographical unit that covers itself) and returns if it finds something that matches with given name. If there isn't any match, it raises a `ValueError`.
- `get_times`: `(region: Region) -> PrayerTimes` => Returns prayer times for the current day
