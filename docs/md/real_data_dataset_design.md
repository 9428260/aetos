# 실데이터 세트 DB 설계 (원형 보존 + 쿼리 기반 테스트)

## 1. 목표

| 목표 | 설명 |
|------|------|
| **원형 보존** | `real.pkl`이 담는 논리 구조(메타데이터, ELIA 계열 시계열, 그리드, 프로슈머, 대용량 `timeseries`)를 DB에서도 **동일한 의미 단위**로 복원 가능하게 둔다. |
| **테이블 적재** | pickle/CSV 등에서 **정규화된 테이블**로 적재해 인덱스·조인·집계가 가능하게 한다. |
| **테스트 연동** | 애플리케이션/단위 테스트는 **필요한 슬라이스만 SQL(또는 뷰)로 조회**해 `EnergyState` 등 도메인 객체로 매핑한다. pickle 직접 의존을 테스트 경로에서 분리한다. |

## 2. 기존 스키마와의 관계

- **`episodes` / `kpi`**: AETOS **운영·시뮬레이션 실행 이력** (워크플로 결과, KPI).
- **실데이터 세트**: **외부/재현 데이터셋** (ELIA·IEEE 스타일 번들).  
  → **별도 테이블군**으로 두고, 필요 시 `Episode.state`에 `dataset_id`·`slice` 참조를 넣는 것은 **선택** (후속 단계).

권장: 1차에서는 **스키마 분리 없이** 테이블 이름 접두어로 구분 (`dataset_*` 또는 `real_*`).

## 3. 논리 모델 (pickle 원형과 1:1 대응)

```
metadata (dict)
    → dataset 단일 행의 JSONB + 주요 필드 중복 인덱스

elia_raw      (DataFrame)  → dataset_elia_raw
elia_internal (DataFrame)  → dataset_elia_internal
grid          (dict of DF) → dataset_grid_buses / branches / generators
prosumers     (DataFrame)  → dataset_prosumers
timeseries    (DataFrame)  → dataset_timeseries (파티션·대용량)
```

각 테이블은 **`dataset_id`** 로 묶인다. 한 번에 여러 버전/출처의 번들을 넣을 수 있다.

## 4. 물리 스키마 (제안)

### 4.1 `dataset` (번들 루트)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | UUID PK | |
| `slug` | TEXT UNIQUE | 예: `elia_ieee141_v1` |
| `name` | TEXT | `metadata.name` |
| `time_resolution_minutes` | INT | 예: 15 |
| `metadata` | JSONB | **원본 `metadata` dict 전체** (경고·컬럼 설명 등 보존) |
| `imported_at` | TIMESTAMPTZ | |
| `source_uri` | TEXT NULL | 파일 경로·S3 등 (선택) |

**원형 보존**: `metadata` JSONB에 `warning`, `elia_raw_columns` 등 **추가 필드 전부** 유지.

### 4.2 `dataset_prosumers`

pickle `prosumers` DataFrame 컬럼을 **그대로** 컬럼화 (스키마 고정이 어려우면 `attributes JSONB` + 필수 키만 컬럼).

| 컬럼 | 타입 |
|------|------|
| `dataset_id` | UUID FK → dataset ON DELETE CASCADE |
| `bus` | INT |
| `prosumer_type` | TEXT |
| `has_*`, `*_kw_cap`, `*_kwh_cap`, `load_scale` | DOUBLE / INT / BOOL (원본 타입에 맞춤) |

PK: `(dataset_id, bus)`

### 4.3 `dataset_timeseries` (대용량)

| 컬럼 | 타입 |
|------|------|
| `dataset_id` | UUID |
| `timestamp` | TIMESTAMPTZ |
| `bus` | INT |
| `prosumer_type` | TEXT |
| `load_kw`, `pv_kw`, `wt_kw`, `bess_soc_kwh`, `bess_ref_power_kw`, `controllable_load_kw`, `cdg_kw_cap` | DOUBLE |
| `price_buy`, `price_sell`, `price_p2p` | DOUBLE |
| `split` | TEXT (train/val/test 등) |

**인덱스 (필수)**:

- `(dataset_id, bus, timestamp)` — 시계열 슬라이스
- `(dataset_id, split)` — 테스트용 train만 등

**파티셔닝 (권장)**: `PARTITION BY RANGE (timestamp)` 월 단위 등 — 데이터 양(백만 행+) 대비.

### 4.4 `dataset_elia_raw` / `dataset_elia_internal`

각각 pickle의 `elia_raw`, `elia_internal` 컬럼 세트를 반영.

- 공통: `dataset_id`, `timestamp` (PK 일부)
- `elia_raw`: `afrr_up_mw`, `mfrr_*` …
- `elia_internal`: `solar_proxy`, `wind_proxy`, `load_proxy`, `price_buy`, `price_sell`

### 4.5 `dataset_grid_buses` / `dataset_grid_branches` / `dataset_grid_generators`

`grid['buses']` 등 DataFrame 컬럼을 그대로 테이블화. PK는 `(dataset_id, …)` + 그리드 식별자(예: bus 번호, branch id).

## 5. 적재(Import) 파이프라움

1. **Python 로더** (기존 `real.pkl` 읽기): pandas DataFrame → `COPY` 또는 `execute_many` 배치 삽입.
2. **트랜잭션**: `dataset` 행 생성 → 자식 테이블 순서로 bulk insert.
3. **검증**: 행 수·`min(timestamp)`/`max(timestamp)`·`bus` 유니크 수를 `metadata`와 교차 확인.

대용량은 **청크 단위 INSERT** + 연결 풀 튜닝.

## 6. 쿼리·뷰 (테스트·앱 공통)

### 6.1 뷰 예시: 시간 집계 (EnergyState 24포인트용)

- **목적**: 15분 → 1시간 평균, 특정 `dataset_id`, `bus`, `[day_start, day_end)` 구간.
- **구현**: `CREATE VIEW dataset_v_hourly_timeseries AS …` 또는 테스트 전용 **SQL 템플릿**을 Python에 두고 파라미터 바인딩.

예시 논리 (의사 SQL):

```sql
SELECT date_trunc('hour', timestamp) AS h,
       avg(load_kw), avg(pv_kw + wt_kw), avg(price_buy)
FROM dataset_timeseries
WHERE dataset_id = :id AND bus = :bus
  AND timestamp >= :t0 AND timestamp < :t1
GROUP BY 1 ORDER BY 1;
```

### 6.2 테스트용 “슬라이스” 쿼리 계약

테스트 코드는 다음 **입력**만 받도록 고정한다.

| 파라미터 | 의미 |
|----------|------|
| `dataset_id` 또는 `slug` | 어떤 번들 |
| `bus` | 프로슈머 버스 |
| `day` / `t0`, `t1` | 하루 또는 구간 |

**출력**: 24행(시간) 또는 96행(15분) → 파이썬에서 `EnergyState`로 매핑 (`tests/real_pkl_loader` 로직과 동일 수식, 단 **소스가 DB**).

## 7. 테스트 전략

| 레벨 | 방법 |
|------|------|
| **로컬/CI DB 없음** | `@pytest.mark.skipif` 또는 SQLite 인메모리에 **최소 시드**(수십 행)만 넣는 fixture — 동일 SQL 계약 유지. |
| **CI with Postgres** | `docker compose up db` 후 마이그레이션 + 소량 seed SQL 또는 `pytest` 스코프에서 한 번만 import. |
| **통합** | `slug='test_seed'` 데이터셋만 조회하는 테스트로 **쿼리 경로** 검증. |

원칙: **비즈니스 매핑(15분→1시간, 단위 환산)** 은 한 모듈에만 두고, 테스트는 **“DB에서 읽은 값 → 그 모듈”** 을 검증한다.

## 8. 마이그레이션·코드 배치

- **ORM**: `src/aetos/db/models_dataset.py` (또는 `real_data.py`) 에 `Dataset`, `DatasetTimeseries`, … 선언.
- **마이그레이션**: Alembic 도입 권장 (장기). 단기는 기존 `init_db` + `upgrade_schema` 패턴에 **CREATE TABLE IF NOT EXISTS** 추가 가능.
- **설정**: `DATABASE_URL` 동일 DB 내 테이블 추가 — 별도 DB 불필요.

## 9. 리스크·결정 사항 (추후 확정)

| 항목 | 선택지 |
|------|--------|
| 단위 | `price_buy`가 €/MWh인지 등 — `metadata` + 코드 상수로 문서화 |
| pickle | DB 적재 후 **원본 바이너리 보관** 여부 (`dataset.raw_blob BYTEA`) — 재현성 vs 용량 |
| `Episode` 연결 | 실험 시 `Episode.state`에 `dataset_ref` JSON 필드 추가 여부 |

## 10. 구현 순서 (권장)

1. `dataset` + `dataset_prosumers` + `dataset_timeseries` 최소 스키마 + 인덱스  
2. import 스크립트 (pkl → DB)  
3. 뷰 또는 Python 쿼리 헬퍼 + `EnergyState` 빌더  
4. pytest: Postgres 또는 SQLite seed + 쿼리 기반 fixture  
5. 필요 시 파티션·Alembic·`raw_blob`

---

이 문서는 **설계 합의용**이며, 구현 시 컬럼 타입·NULL 허용은 실제 `real.pkl` dtypes에 맞춰 조정한다.
