from __future__ import annotations

import math
import uuid
from datetime import datetime
from typing import Any

from asyncua import ua

_INTEGER_RANGES = {
    ua.VariantType.SByte: (-(2**7), 2**7 - 1),
    ua.VariantType.Byte: (0, 2**8 - 1),
    ua.VariantType.Int16: (-(2**15), 2**15 - 1),
    ua.VariantType.UInt16: (0, 2**16 - 1),
    ua.VariantType.Int32: (-(2**31), 2**31 - 1),
    ua.VariantType.UInt32: (0, 2**32 - 1),
    ua.VariantType.Int64: (-(2**63), 2**63 - 1),
    ua.VariantType.UInt64: (0, 2**64 - 1),
}
_FLOAT32_MAX = 3.4028234663852886e38


def coerce_value(value: Any, vtype: ua.VariantType) -> Any:
    """
    북향 노드가 선언한 데이터 형식에 맞게 값을 변환한다.

    asyncua 서버는 선언과 다른 형식의 값도 그대로 받아들이므로, 상위 시스템이 형식 오류를 겪지 않도록 여기서 맞춘다.
    정수 형식에 소수가 들어오면 반올림한다. 변환할 수 없으면 TypeError/ValueError/OverflowError 를 낸다.
    """
    if vtype is ua.VariantType.Boolean:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and value in (0, 1):
            return bool(value)
        raise TypeError(f"Boolean 으로 변환할 수 없습니다: {value!r}")

    if vtype in _INTEGER_RANGES:
        if isinstance(value, float):
            value = round(value)
        elif isinstance(value, bool):
            value = int(value)
        elif not isinstance(value, int):
            raise TypeError(f"{vtype.name} 로 변환할 수 없습니다: {value!r}")
        low, high = _INTEGER_RANGES[vtype]
        if not low <= value <= high:
            raise OverflowError(f"{vtype.name} 범위({low}~{high})를 벗어났습니다: {value}")
        return value

    if vtype in (ua.VariantType.Float, ua.VariantType.Double):
        if not isinstance(value, (int, float)):
            raise TypeError(f"{vtype.name} 로 변환할 수 없습니다: {value!r}")
        number = float(value)
        if vtype is ua.VariantType.Float and math.isfinite(number) and abs(number) > _FLOAT32_MAX:
            raise OverflowError(f"Float 범위를 벗어났습니다: {number}")
        return number

    if vtype is ua.VariantType.String:
        return value if isinstance(value, str) else str(value)

    expected = {
        ua.VariantType.DateTime: datetime,
        ua.VariantType.Guid: uuid.UUID,
        ua.VariantType.ByteString: bytes,
    }.get(vtype)
    if expected is not None and isinstance(value, expected):
        return value
    raise TypeError(f"{vtype.name} 로 변환할 수 없습니다: {value!r}")
