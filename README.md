# OPC-UA Middleware Gateway

## 개요

이 프로젝트는 현장 OPC-UA 서버에서 데이터를 수집하고, 이를 상위 시스템에 다시 OPC-UA 방식으로 제공하는 게이트웨이입니다.

게이트웨이는 동시에 두 가지 역할을 수행합니다.

- 현장 설비와 연결할 때는 **OPC-UA 클라이언트**
- 상위 시스템과 연결할 때는 **OPC-UA 서버**

이를 통해 상위 시스템은 설비 제조사별 OPC-UA 구조를 직접 이해하지 않아도, 게이트웨이가 제공하는 일관된 주소와 구조로 데이터를 조회할 수 있습니다.

## 전체 구조

```mermaid
flowchart LR
    A[현장 OPC-UA 서버<br>PLC·설비·센서]
    B[Discovery<br>노드 탐색]
    C[태그 카탈로그<br>수집·변환 규칙]
    D[Runtime Collector<br>데이터 구독]
    E[북향 OPC-UA 서버<br>표준화된 데이터 제공]
    F[상위 시스템<br>MES·SCADA·다른 게이트웨이]

    A --> B
    B --> C
    C --> D
    A --> D
    D --> E
    E --> F
```

## 핵심 운영 방식

게이트웨이는 노드 탐색과 실제 데이터 수집을 분리합니다.

### 1. Discovery: 노드 탐색

Discovery는 현장 OPC-UA 서버의 주소 공간을 탐색하는 과정입니다.

주요 역할은 다음과 같습니다.

- 서버가 제공하는 설비와 센서 노드 확인
- NodeId, 네임스페이스, 데이터 형식 등의 정보 수집
- 탐색 결과를 태그 카탈로그 후보로 생성
- 기존 카탈로그와 비교하여 추가·변경·삭제된 노드 확인

Discovery 결과가 즉시 운영에 반영되는 것은 아닙니다. 필요한 태그를 검토하고 활성화한 뒤 Runtime에서 사용합니다.

#### 실행 방법

```bash
# 현장 서버 전체를 탐색해 카탈로그(catalog/tags.yaml)에 신규 후보를 추가
python main.py discover

# 파일은 바꾸지 않고 결과만 확인
python main.py discover --dry-run

# 특정 설비 아래만 탐색
python main.py discover --root "ns=2;s=Line01"
```

접속할 서버와 카탈로그 위치는 `.env`의 `OPCUA_ENDPOINT`, `OPCUA_SERVER_ID`, `CATALOG_PATH`로 지정합니다.

#### 다시 실행하면 어떻게 되나요?

Discovery는 여러 번 실행해도 안전합니다. 운영자가 검토한 내용은 덮어쓰지 않습니다.

- **새로 발견된 노드**: `candidate` 상태, 비활성(`enabled: false`)으로 카탈로그에 추가
- **이미 있는 태그**: 그대로 유지하고, 경로나 데이터 형식이 바뀌었으면 `[변경]`으로 알림
- **서버에서 사라진 노드**: 삭제하지 않고 `[누락]`으로 알림 (일부만 탐색한 경우에는 확인하지 않음)

탐색 시 표준 OPC-UA 노드(Server 객체 등)와 Property는 태그 후보에서 제외합니다. 단, 단위 정보(EngineeringUnits)는 읽어서 `unit`에 채웁니다.

### 2. Runtime: 데이터 수집 및 제공

Runtime은 승인된 태그 카탈로그를 읽고 실제 데이터를 처리합니다.

주요 역할은 다음과 같습니다.

1. 현장 OPC-UA 서버에 접속
2. 카탈로그에 활성화된 노드 구독
3. 값과 품질 상태, 발생 시각 수신
4. 북향 OPC-UA 서버의 대응 노드 갱신
5. 상위 시스템에 일관된 구조로 데이터 제공

Runtime은 서버 전체를 반복 탐색하지 않습니다. 카탈로그에 등록된 노드만 구독하므로 동작이 예측 가능하고 불필요한 부하를 줄일 수 있습니다.

## 태그 카탈로그

태그 카탈로그는 다음 관계를 정의하는 설정 정보입니다.

> 현장 서버의 어떤 데이터를 수집하여, 게이트웨이의 어떤 노드로 제공할 것인가?

카탈로그는 단순한 노드 목록이 아니라 현장 데이터와 상위 시스템 사이의 변환 규칙입니다.

### 권장 필드

#### 식별 정보

- `tag_id`: 게이트웨이 내부에서 사용하는 고유 식별자
- `name`: 사람이 이해할 수 있는 태그 이름
- `description`: 태그 용도에 대한 설명
- `enabled`: 실제 수집 및 제공 여부
- `status`: 후보, 승인, 사용 중, 중지 등의 관리 상태

#### 현장 서버 정보

- `source_server`: 접속할 현장 서버 식별자
- `source_namespace_uri`: 노드가 속한 네임스페이스 URI
- `source_identifier`: 원본 노드의 식별자 (`s=문자열` 또는 `i=숫자` 형식)
- `source_browse_path`: 사람이 확인하기 위한 노드 경로
- `source_data_type`: 현장 서버가 제공하는 원본 데이터 형식

네임스페이스 번호(`ns=2` 등)는 서버 재시작이나 설정 변경으로 달라질 수 있습니다. 따라서 번호 대신 변하지 않는 Namespace URI를 저장합니다.

#### 북향 OPC-UA 서버 정보

- `target_path`: 게이트웨이에서 제공할 노드 경로
- `target_name`: 상위 시스템에 표시할 이름
- `data_type`: 제공할 OPC-UA 데이터 형식
- `unit`: 온도, 압력, 속도 등의 공학 단위

#### 수집 정책

- `sampling_interval_ms`: 현장 데이터 확인 주기
- `publishing_interval_ms`: 구독 데이터 전달 주기
- `deadband`: 의미 없는 미세 변화의 전달을 줄이기 위한 기준

#### 값 변환

- `scale`: 원본 값에 적용할 배율
- `offset`: 원본 값에 더할 보정값

변환식은 다음과 같습니다.

```text
제공값 = 원본값 × scale + offset
```

### 카탈로그 예시

```yaml
tags:
  - tag_id: bearing_temperature_01
    name: 1번 베어링 온도
    description: 1번 모터의 베어링 온도
    enabled: true
    status: active

    source:
      server: production_line_01
      namespace_uri: http://vendor.example.com/machine
      identifier: s=Machine01.Bearing.Temperature
      browse_path: Machine01/Bearing/Temperature
      data_type: Double

    target:
      path: Factory/Line01/Machine01/Bearing
      name: Temperature
      data_type: Double
      unit: degC

    collection:
      sampling_interval_ms: 1000
      publishing_interval_ms: 1000
      deadband: 0.1

    conversion:
      scale: 1.0
      offset: 0.0
```

초기 구현에서는 YAML, JSON 또는 CSV 파일을 사용할 수 있습니다. 설정이 복잡해지거나 변경 이력과 승인 절차가 필요해지면 데이터베이스로 확장할 수 있습니다.

## 북향 OPC-UA 주소 공간

게이트웨이가 제공하는 OPC-UA 주소 공간은 현장 서버의 구조를 그대로 복제하지 않습니다.

현장 제조사나 설비 종류가 달라도 상위 시스템에서는 동일한 규칙으로 접근할 수 있도록 단순하고 안정적인 구조를 제공합니다.

예시:

```text
Objects
└── Factory
    └── Line01
        └── Machine01
            ├── Temperature
            ├── Pressure
            └── OperationStatus
```

북향 노드 구조와 NodeId는 가능한 한 변경하지 않습니다. 현장 서버의 NodeId가 바뀌더라도 카탈로그의 매핑만 수정하여 상위 시스템에 미치는 영향을 줄입니다.

각 데이터 노드는 값뿐 아니라 다음 정보도 함께 제공해야 합니다.

- 현재 값
- 데이터 품질 상태
- 현장에서 값이 생성된 시각
- 게이트웨이가 값을 수신한 시각
- 데이터 단위와 형식

## NodeSet XML의 역할

NodeSet XML은 북향 OPC-UA 서버가 제공할 주소 공간과 타입을 표준화하는 데 사용할 수 있습니다.

초기 단계에서는 코드와 카탈로그를 이용해 노드를 구성할 수 있습니다. 이후 여러 게이트웨이에 같은 모델을 배포하거나 외부 시스템과 모델을 공유해야 한다면 NodeSet2 XML 도입을 검토합니다.

가능하면 자체 규격을 처음부터 새로 만들기보다 OPC Foundation의 표준 모델이나 산업별 Companion Specification을 우선 검토합니다.

## 주요 구성 요소

프로젝트는 다음 구성 요소로 구분합니다.

```text
Discovery
  현장 OPC-UA 서버 탐색 및 카탈로그 후보 생성

Catalog
  수집할 노드와 북향 노드 사이의 매핑 관리

Collector
  카탈로그에 등록된 현장 노드 구독

Data Mapping
  데이터 형식, 단위, 스케일 및 경로 변환

Northbound OPC-UA Server
  변환된 데이터를 상위 시스템에 제공
```

Discovery와 Runtime은 코드와 실행 명령을 분리합니다. 이를 통해 탐색 작업이 운영 중인 데이터 수집에 영향을 주지 않도록 합니다.

## 현재 개발 범위

우선 구현할 범위는 다음과 같습니다.

- 현장 OPC-UA 서버 주소 공간 탐색
- 탐색 결과를 이용한 태그 카탈로그 생성
- 카탈로그 기반 데이터 구독
- 북향 OPC-UA 주소 공간 생성
- 수집한 값을 북향 노드에 반영
- Discovery와 Runtime 실행 모드 분리

다음 항목은 기본 구조가 완성된 후 단계적으로 검토합니다.

- 연결 장애 및 자동 복구 고도화
- 인증서와 암호화를 포함한 운영 보안
- 서버 모델 변경 자동 감지
- NodeSet2 XML 기반 모델 배포
- 카탈로그 승인 및 변경 이력 관리
