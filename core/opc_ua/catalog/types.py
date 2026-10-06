"""카탈로그 `data_type` 에 쓸 수 있는 OPC UA 기본 데이터 형식."""

INTEGER_DATA_TYPES = frozenset({"SByte", "Byte", "Int16", "UInt16", "Int32", "UInt32", "Int64", "UInt64"})
FLOAT_DATA_TYPES = frozenset({"Float", "Double"})
NUMERIC_DATA_TYPES = INTEGER_DATA_TYPES | FLOAT_DATA_TYPES

SUPPORTED_DATA_TYPES = NUMERIC_DATA_TYPES | {"Boolean", "String", "DateTime", "Guid", "ByteString"}
