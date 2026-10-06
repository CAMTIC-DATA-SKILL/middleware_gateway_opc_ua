"""
카탈로그 `unit` 표기를 OPC UA 표준 단위(UNECE Recommendation 20)로 변환한다.

SCADA 등 상위 시스템은 단위 표시 이름보다 UnitId 로 단위를 판단하는 경우가 많다.
표에 없는 단위는 표시 이름만 제공한다.
"""

from __future__ import annotations

from dataclasses import dataclass

UNECE_NAMESPACE_URI = "http://www.opcfoundation.org/UA/units/un/cefact"


@dataclass(frozen=True)
class UnitInfo:
    code: str
    symbol: str
    description: str

    @property
    def unit_id(self) -> int:
        """OPC UA 규격: UNECE 공통 코드의 각 문자를 1바이트씩 이어 붙인 정수 (예: CEL -> 4408652)."""
        value = 0
        for char in self.code:
            value = (value << 8) | ord(char)
        return value


_DEFINITIONS: tuple[tuple[tuple[str, ...], UnitInfo], ...] = (
    (("°C", "degC", "℃"), UnitInfo("CEL", "°C", "degree Celsius")),
    (("°F", "degF", "℉"), UnitInfo("FAH", "°F", "degree Fahrenheit")),
    (("K",), UnitInfo("KEL", "K", "kelvin")),
    (("bar",), UnitInfo("BAR", "bar", "bar")),
    (("mbar",), UnitInfo("MBR", "mbar", "millibar")),
    (("Pa",), UnitInfo("PAL", "Pa", "pascal")),
    (("kPa",), UnitInfo("KPA", "kPa", "kilopascal")),
    (("MPa",), UnitInfo("MPA", "MPa", "megapascal")),
    (("psi",), UnitInfo("PS", "psi", "pound-force per square inch")),
    (("mm/s",), UnitInfo("C16", "mm/s", "millimetre per second")),
    (("m/s",), UnitInfo("MTS", "m/s", "metre per second")),
    (("rpm", "r/min"), UnitInfo("RPM", "r/min", "revolutions per minute")),
    (("Hz",), UnitInfo("HTZ", "Hz", "hertz")),
    (("V",), UnitInfo("VLT", "V", "volt")),
    (("mV",), UnitInfo("2Z", "mV", "millivolt")),
    (("A",), UnitInfo("AMP", "A", "ampere")),
    (("mA",), UnitInfo("4K", "mA", "milliampere")),
    (("W",), UnitInfo("WTT", "W", "watt")),
    (("kW",), UnitInfo("KWT", "kW", "kilowatt")),
    (("MW",), UnitInfo("MAW", "MW", "megawatt")),
    (("Wh",), UnitInfo("WHR", "Wh", "watt hour")),
    (("kWh",), UnitInfo("KWH", "kWh", "kilowatt hour")),
    (("%",), UnitInfo("P1", "%", "percent")),
    (("m",), UnitInfo("MTR", "m", "metre")),
    (("cm",), UnitInfo("CMT", "cm", "centimetre")),
    (("mm",), UnitInfo("MMT", "mm", "millimetre")),
    (("kg",), UnitInfo("KGM", "kg", "kilogram")),
    (("g",), UnitInfo("GRM", "g", "gram")),
    (("t",), UnitInfo("TNE", "t", "tonne")),
    (("s", "sec"), UnitInfo("SEC", "s", "second")),
    (("ms",), UnitInfo("C26", "ms", "millisecond")),
    (("min",), UnitInfo("MIN", "min", "minute")),
    (("h",), UnitInfo("HUR", "h", "hour")),
    (("l", "L"), UnitInfo("LTR", "l", "litre")),
    (("l/min", "L/min"), UnitInfo("L2", "l/min", "litre per minute")),
    (("m³", "m3"), UnitInfo("MTQ", "m³", "cubic metre")),
    (("m³/h", "m3/h"), UnitInfo("MQH", "m³/h", "cubic metre per hour")),
    (("N",), UnitInfo("NEW", "N", "newton")),
    (("N·m", "Nm", "N.m"), UnitInfo("NU", "N·m", "newton metre")),
)

_BY_ALIAS = {alias: unit for aliases, unit in _DEFINITIONS for alias in aliases}


def lookup_unit(text: str) -> UnitInfo | None:
    """대소문자를 구분한다 (mA: 밀리암페어, MA: 메가암페어)."""
    return _BY_ALIAS.get(text.strip())
