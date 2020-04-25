from __future__ import annotations

import json
import os
import shelve
from argparse import ArgumentParser
from dataclasses import asdict, dataclass, field
from datetime import time
from enum import IntEnum
from functools import partial, partialmethod
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Dict, Iterator, Type, TypeVar
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE_URL = "https://namazvakitleri.diyanet.gov.tr"
CACHE_PRIORITY = ("DIYANET_CACHE_HOME", "XDG_CACHE_HOME")

RecordStates = IntEnum("RecordStates", "NAME VALUE")
shadow_field = partial(field, repr=False)


@dataclass
class GeographicUnit:
    name: str
    idx: int


@dataclass
class Country(GeographicUnit):
    pass


@dataclass
class State(GeographicUnit):
    country: Country = shadow_field()


@dataclass
class Region(GeographicUnit):
    url: str
    country: Country = shadow_field()
    state: State = shadow_field()


@dataclass
class PrayerTimes:
    fajr: time
    sunrise: time
    dhuhr: time
    asr: time
    maghrib: time
    isha: time


def _get_cache_dir() -> Path:
    for option in CACHE_PRIORITY:
        if option in os.environ:
            path = os.environ.get(option)
    else:
        path = "~/.cache"

    path = Path(path).expanduser()
    if path.exists():
        path = path / "diyanet"
        path.mkdir(exist_ok=True)
        return path
    else:
        raise ValueError(
            f"Either one of these {', '.join(CACHE_PRIORITY)} environment"
            f"variables should point to a valid path, or '~/.cache' should "
            f"be available."
        )


class OptionParser(HTMLParser):
    def __init__(self, identifier: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.options = []
        self.identifier = identifier
        self.record_options = False

    def handle_starttag(self, tag, _attr):
        attributes = dict(_attr)
        if (
            tag == "select"
            and "class" in attributes
            and self.identifier in attributes["class"]
        ):
            self.record_options = True
        elif self.record_options and tag == "option":
            self.options.append([None, int(attributes["value"])])

    def handle_data(self, data):
        if (
            self.record_options
            and self.lasttag == "option"
            and self.options[-1][0] is None
        ):
            self.options[-1][0] = data.casefold()

    def handle_endtag(self, tag):
        if tag == "select" and self.record_options:
            self.record_options = False
            self.options.sort(key=lambda t: t[1])


UnitType = TypeVar("UnitType", Type[State], Type[Region])


class PrayerTimeParser(HTMLParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.times = []
        self.record_state = None

    def handle_starttag(self, tag, _attr):
        attributes = dict(_attr)
        if tag == "div" and "class" in attributes:
            if attributes["class"] == "tpt-title":
                self.record_state = RecordStates.NAME
            elif attributes["class"] == "tpt-time":
                self.record_state = RecordStates.VALUE

    def handle_data(self, data):
        if self.record_state is None:
            return

        if self.record_state is RecordStates.NAME and (
            len(self.times) == 0 or self.times[-1][1] is not None
        ):
            self.times.append([data.strip(), None])
        elif (
            self.record_state is RecordStates.VALUE
            and self.times[-1][1] is None
        ):
            self.times[-1][1] = data
        else:
            self.times.pop()

    def handle_endtag(self, tag):
        self.record_state = None


class Diyanet:
    def __init__(
        self,
        *,
        db_path: os.PathLike = _get_cache_dir() / "db",
        base_url: str = BASE_URL,
    ) -> None:
        self.base_url = base_url

        cache_db = shelve.open(os.fspath(db_path))
        self.initalize_db(cache_db)

    def initalize_db(self, db: shelve.Shelf) -> None:
        for section in "page", "countries", "regions":
            if section not in db:
                initalizer = getattr(self, f"initalize_{section}", dict)
                db[section] = initalizer()
            setattr(self, f"_{section}_cache", db[section])

    def initalize_countries(self) -> Dict[str, Country]:
        page = self.fetch("/tr-TR/home")
        country_parser = OptionParser(identifier="country-select")
        country_parser.feed(page)
        return {
            country: Country(country, idx)
            for country, idx in country_parser.options
        }

    def do_request(self, request: Request) -> str:
        address = request.get_full_url()
        if address in self._page_cache:
            return self._page_cache[address]

        with urlopen(request) as page:
            self._page_cache[address] = content = page.read().decode()

        return content

    def fetch(self, endpoint: str, **kwargs) -> str:
        request = Request(f"{self.base_url}{endpoint}?" + urlencode(kwargs))
        return self.do_request(request)

    def get_countries(self) -> Iterator[Country]:
        yield from self._countries_cache.values()

    def get_states(self, country: Country) -> Iterator[State]:
        data = json.loads(
            self.fetch(
                "/tr-TR/home/GetRegList",
                ChangeType="country",
                CountryId=country.idx,
            )
        )
        for state in data["StateList"]:
            yield State(state["SehirAdiEn"], state["SehirID"], country)

    def get_regions(self, state: State) -> Iterator[Region]:
        data = json.loads(
            self.fetch(
                "/tr-TR/home/GetRegList",
                ChangeType="state",
                CountryId=state.country.idx,
                StateId=state.idx,
            )
        )
        for region in data["StateRegionList"]:
            yield Region(
                region["IlceAdiEn"],
                region["IlceID"],
                region["IlceUrl"],
                state.country,
                state,
            )

    def get_country(self, name: str) -> Country:
        for country in self.get_countries():
            if name.casefold() == country.name.casefold():
                return country
        else:
            raise ValueError(f"Unknown/unsupported country: '{name}'")

    def _geographic_search(
        self, unit: UnitType, arg: GeographicUnit, name: str
    ) -> UnitType:
        unit_name = unit.__name__.lower()
        lister = getattr(self, f"get_{unit_name}s")
        for listing in lister(arg):
            if name.casefold() == listing.name.casefold():
                return listing
        else:
            raise ValueError(f"Unknown/unsupported {unit_name}: '{name}'")

    get_state = partialmethod(_geographic_search, State)
    get_region = partialmethod(_geographic_search, Region)

    def get_times(self, region: Region) -> PrayerTimes:
        page = self.fetch(region.url)
        parser = PrayerTimeParser()
        parser.feed(page)
        times = dict(parser.times)
        return PrayerTimes(
            time.fromisoformat(times["İmsak"]),
            time.fromisoformat(times["Güneş"]),
            time.fromisoformat(times["Öğle"]),
            time.fromisoformat(times["İkindi"]),
            time.fromisoformat(times["Akşam"]),
            time.fromisoformat(times["Yatsı"]),
        )


def main():
    parser = ArgumentParser()
    parser.add_argument("country")
    parser.add_argument("state")
    parser.add_argument("region")
    options = parser.parse_args()

    connector = Diyanet()
    country = connector.get_country(options.country)
    state = connector.get_state(country, options.state)
    region = connector.get_region(state, options.region)
    for key, value in asdict(connector.get_times(region)).items():
        print(key.title(), "===>", value)


if __name__ == "__main__":
    main()
