# 테스트 및 고도화 문서

## 주요 문제 해결 및 기술 리서치 (테스트 단계)

현재 시스템 테스트 과정에서 발견된 운영 이슈, 저장 안정성 문제, DB/벡터 계층 예외, UI 가시성 문제를 기준으로 정리한다.

### 1. 워크플로우 및 실행 품질 점검

| 항목 | 내용 |
| --- | --- |
| 평가 대상 기능 | `run_workflow`, `Strategy Agent`, `Optimizer Agent`, `Critic Agent`, `Dispatch Agent`, `Deep Agent` |
| 평가 방식 | `/run` 응답, `step_events`, `messages`, reward, `/episodes`, `/kpi`, dispatch log 기준 점검 |
| 초기 관찰 결과 | 전략 생성과 실행은 동작하지만, DB 연결 실패 시 이력이 누적되지 않고 memory fallback으로만 남는 문제가 확인됨 |
| 문제 원인 | 로컬 `.env`의 `DATABASE_URL` 포트와 `docker-compose`의 PostgreSQL 노출 포트가 불일치함 |
| 개선 조치 | `.env`의 DB 포트를 `5433`으로 수정하고, Docker 기반 실행 경로와 로컬 실행 경로를 분리해 정리 |
| 개선 후 결과 | DB 연결 성공 시 episode, KPI, strategy memory가 정상 누적되고 `/episodes` 기반 이력 조회가 가능해짐 |
| 비고 | DB 실패 시 `_mem_episodes` fallback은 유지하여 API 자체는 중단되지 않도록 설계됨 |

### 2. DB 및 pgvector 연동 안정화

| 항목 | 내용 |
| --- | --- |
| 기존 병목 | PostgreSQL 연결 직후 `pgvector` codec 등록 과정에서 초기화 실패 |
| 초기 문제 | `run_sync` 호출 방식이 현재 asyncpg 어댑터와 맞지 않아 loop와 API가 startup 단계에서 실패 |
| 원인 분석 | SQLAlchemy async + asyncpg 환경에서 `dbapi_connection`이 `run_sync`가 아닌 `run_async` 경로를 사용해야 함 |
| 개선 조치 | `src/aetos/db/session.py`에서 codec 등록을 `run_async` 우선 방식으로 수정 |
| 추가 문제 | `vector` extension 생성 전 codec 등록이 먼저 실행되어 `unknown type: public.vector` 예외 발생 |
| 추가 개선 | `public.vector` 타입이 아직 없는 초기 연결에서는 codec 등록 예외를 무시하고 DB 초기화가 먼저 진행되도록 처리 |
| 개선 후 결과 | `init_db()`가 정상 진행되고, 이후 새 연결부터 `pgvector` 사용 가능 |
| 비고 | vector 사용 불가 시에도 검색은 in-memory fallback으로 계속 동작 |

### 3. Docker 실행 구조 정리

| 항목 | 내용 |
| --- | --- |
| 발견된 문제 | `mcp` 서비스가 별도 compose 서비스로 실행되지만 실제로는 stdio 기반이라 바로 종료됨 |
| 원인 분석 | FastAPI 앱이 이미 `/mcp` 경로에 MCP SSE를 mount하고 있어 독립 `mcp` 컨테이너가 구조적으로 중복됨 |
| 개선 조치 | `docker-compose.yml`에서 `mcp` 서비스를 제거하고 `db + api + loop` 구조로 단순화 |
| 개선 후 결과 | 실행 구조가 명확해졌고, MCP는 `http://localhost:8000/mcp`로 일원화됨 |
| 운영 효과 | compose 실행 시 불필요한 종료 로그가 사라지고, 운영자가 서비스 구조를 더 쉽게 이해 가능 |

### 4. 예외 처리 및 가드레일

| 항목 | 내용 |
| --- | --- |
| 차단 대상 | DB 연결 실패, vector search 실패, deep agent 실패, 정책 위반 전략, 실행 불가 전략 |
| 탐지 방식 | startup 예외, `try/except` fallback, critic filtering, dispatch validation |
| 초기 문제 | 저장 실패 시 이력이 전혀 안 쌓이는 것으로 오인될 수 있었고, vector 계층 장애가 전체 기능 실패로 이어질 위험이 있었음 |
| 대응 로직 | DB 실패 시 `_mem_episodes` fallback, vector search 실패 시 cosine fallback, deep agent 실패 시 workflow fallback 유지 |
| 테스트 결과 | 저장 계층 일부 실패 상황에서도 `/run`, `/chat`, `/episodes` 기본 동작은 유지됨 |
| 추가 가드레일 | critic 단계에서 제약 위반 후보를 제외하고, dispatch는 idempotency 정책과 power/price 한계를 유지 |

### 5. 테스트 환경 및 재현성 이슈

| 항목 | 내용 |
| --- | --- |
| 발견된 문제 | 로컬 테스트 실행 시 `pgvector` 미설치로 `pytest` 수집 단계에서 실패 |
| 증상 | `ModuleNotFoundError: No module named 'pgvector'` |
| 원인 분석 | 현재 로컬 Python 환경과 프로젝트 의존성이 완전히 맞지 않음 |
| 개선 방향 | Python 3.12 기반 가상환경 또는 Docker 내부 기준으로 테스트 환경을 통일할 필요가 있음 |
| 현재 상태 | 테스트 1회 실행은 수행했으나, 로컬 환경 의존성 부족으로 collection error 확인 |
| 운영 판단 | 기능 검증은 Docker 실행 기준으로 우선 확인하고, 로컬 테스트 환경은 별도 정비 대상으로 관리 |

### 6. UI 및 가시성 문제 해결

| 항목 | 내용 |
| --- | --- |
| 발견된 문제 | 사용자는 “이력이 안 쌓인다”로 인식했으나 실제로는 DB 미연결로 memory fallback만 동작하고 있었음 |
| 원인 분석 | `/episodes`는 DB 우선 조회 후 실패 시 메모리 fallback으로 동작하므로, 재시작 이후 이력이 사라지면 원인 파악이 어려움 |
| 개선 방향 | dashboard 또는 API 로그에서 DB fallback 상태를 더 명확히 표시할 필요가 있음 |
| 현재 상태 | 원인은 포트 mismatch와 DB startup 예외로 확인되었고, 설정 수정으로 재현 경로가 정리됨 |
| 추가 개선 포인트 | 대시보드에 DB 저장 상태, fallback 여부, 마지막 persist 성공 여부를 표시하면 운영성이 향상될 수 있음 |

### 7. 기타 문제 해결 사례

- `.env`의 `DATABASE_URL`을 Docker DB 포트 `5433` 기준으로 수정
- `pgvector` codec 등록 로직을 현재 asyncpg 방식에 맞게 수정
- `unknown type: public.vector` 예외를 초기 부팅 시 허용해 DB schema 초기화가 먼저 되도록 조정
- `docker-compose.yml`에서 중복된 `mcp` 서비스 제거
- 이력 미저장 문제의 실제 원인이 “저장 로직 부재”가 아니라 “DB 연결 실패 후 memory fallback”임을 분리해 확인
- 커밋 `설정 변경후 테스트 1회 실행` 및 원격 푸시 완료

## 테스트 결과 요약

현재 시스템 기준 테스트에서는 핵심 기능 자체보다 **운영 안정성, 저장 계층 연결성, Docker 실행 구조, vector 계층 초기화 순서**가 주요 이슈로 확인되었다. 특히 이력 누적 문제는 workflow 자체의 버그가 아니라 DB 연결 실패와 startup 초기화 예외에서 비롯된 운영 환경 문제였다.

이번 고도화로 다음 항목이 개선되었다.

- DB 기반 episode/KPI 저장 경로 정상화
- pgvector 초기화 안정성 확보
- Docker 서비스 구조 단순화
- fallback 경로의 동작 원인 명확화
- 실행/저장/조회 흐름의 재현 가능성 향상

향후 고도화 과제는 다음과 같다.

- 대시보드에 DB 저장 성공/실패 상태 시각화
- 로컬 테스트 환경과 Docker 테스트 환경 일원화
- critic 및 dispatch 단계의 상세 explainability 강화
- strategy memory 검색 결과의 운영 UI 노출
- `/chat`와 `/run` 결과를 통합한 운영 리포트 제공
