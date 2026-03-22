# POC 모듈 구현 문서

## 핵심 구현 내용

### 1.1 에이전트 워크플로우 (Agent Workflow)

* 구현 기능: 현재 시스템은 AETOS의 단계형 workflow를 기반으로 **전략 생성 → 최적화 → 선택 → 정책 검토 → dispatch → 이력 저장**까지 연결되는 통합 운영 파이프라인을 구현한다.

* 동작 원리:

  * 현재 workflow는 `generate → optimize → auction → critique → dispatch` 순으로 실행된다.
  * `generate` 단계에서 전략 후보를 생성하고, `optimize` 단계에서 후보를 개선한다.
  * `auction` 단계에서 후보 전략 중 최종 선택 대상을 결정한다.
  * `critique` 단계에서 정책 및 물리 제약을 검토하고 부적합 전략을 제외한다.
  * 승인된 전략만 `dispatch` 단계로 전달되어 ESS charge/discharge, market quantity, PV curtailment가 실행용 setpoint로 변환된다.
  * 실행 이후 `persist_workflow_run()`을 통해 episode, KPI, messages, reward decomposition이 저장되고, 동시에 strategy memory도 축적된다.

* 주요 기술:

  * 단계형 workflow orchestration
  * A2A 기반 runtime 연계
  * critic 기반 제약 필터링
  * dispatch log 생성
  * episode/KPI persistence
  * dashboard history 조회

### 1.2 도구(Tool) 및 함수 연동

* 구현 기능: 현재 시스템은 전략 실행, 정책 검증, dispatch, KPI 집계, 자연어 운영 요청, 유사 전략 검색을 모듈 단위로 연동한다.

* 동작 원리:

  * `run_workflow()`가 전체 전략 생성, 최적화, 선택, dispatch까지 수행한다.
  * `runtime.optimize_via_a2a()`는 상태 기반 최적화 실행 경로를 제공한다.
  * `runtime.policy_check()`는 전략의 정책 및 제약 위반 여부를 검사한다.
  * `runtime.dispatch_via_a2a()`는 승인된 전략을 실제 실행용 action record로 변환한다.
  * `invoke_deep_agent()`는 자연어 요청을 처리하며, 실패 시 workflow fallback을 사용한다.
  * `vector_store.search()`는 현재 상태와 유사한 과거 전략을 검색하고, `vector_store.add_memory()`는 새 전략과 성과를 저장한다.
  * `runtime.kpi()`와 `/kpi` API는 누적 KPI를 제공하고, `/episodes`는 운영 이력을 조회한다.

* 주요 기술:

  * structured dict/JSON 응답
  * A2A runtime abstraction
  * rule-based policy validation
  * async dispatch execution
  * vector memory search
  * FastAPI + MCP tool exposure

### 1.3 데이터 및 메모리 (Memory & Logging)

* 구현 기능: 현재 시스템은 episode history, KPI, strategy memory, dispatch log, workflow messages를 저장 및 조회할 수 있는 운영 메모리 구조를 갖는다.

* 동작 원리:

  * workflow 실행 결과는 `episodes` 테이블에 state, action, reward, step_events, messages, reward decomposition 형태로 저장된다.
  * KPI는 `kpi` 테이블에 episode와 연결되어 저장된다.
  * strategy memory는 `strategy_memory` 테이블에 state summary, strategy, reward, embedding과 함께 저장된다.
  * DB 사용이 불가능한 경우 `_mem_episodes`를 사용해 메모리 기반 fallback 이력을 유지한다.
  * vector search가 실패하는 경우에는 in-memory cosine similarity 검색으로 fallback한다.
  * dispatch 결과는 runtime log를 통해 최근 실행 KPI 계산에 활용된다.

* 주요 기술:

  * PostgreSQL 기반 persistent storage
  * `pgvector` 기반 strategy memory
  * in-memory fallback history
  * workflow messages / step_events 저장
  * KPI aggregation
  * dispatch log 기반 runtime summary

## 주요 문제 해결 및 기술 리서치

| 이슈 구분 | 문제 상황 및 원인 | 리서치 및 해결 과정 (Reference & Solution) |
| --- | --- | --- |
| 이력 저장 안정성 | 실행은 되지만 이력이 누적되지 않는 문제 발생 | 원인 확인 결과 저장 로직 부재가 아니라 DB 연결 실패 후 memory fallback만 동작하고 있었음. `.env`의 `DATABASE_URL` 포트를 `docker-compose`의 `5433`과 일치시키도록 수정 |
| DB 초기화/pgvector | PostgreSQL 연결 시 `pgvector` codec 등록 단계에서 startup 실패 | `run_sync` 호출 방식이 현재 asyncpg 어댑터와 맞지 않아 `run_async` 우선 방식으로 수정. 추가로 `unknown type: public.vector` 예외는 extension 생성 전 초기 연결에서 무시하도록 처리 |
| Docker 서비스 구조 | `mcp` 서비스가 compose에서 별도 실행되지만 stdio 프로세스라 바로 종료됨 | FastAPI 앱이 이미 `/mcp`를 mount하고 있으므로 중복 구조로 판단. `docker-compose.yml`에서 `mcp` 서비스를 제거하고 `db + api + loop` 구조로 단순화 |
| fallback 운영성 | DB 또는 vector 계층 장애 시 전체 기능 실패 위험 | DB 실패 시 `_mem_episodes`, vector 실패 시 in-memory cosine search, deep agent 실패 시 workflow fallback을 유지해 핵심 기능 지속 가능하도록 구성 |
| 테스트 재현성 | 로컬 테스트 환경에서 `pgvector` 미설치로 `pytest` 수집 실패 | Docker 실행 기준으로 우선 검증하고, 로컬 Python 3.12 기반 환경과 의존성 정합성을 맞추는 방향으로 정리. 현재 실패 원인은 기능 버그보다 테스트 환경 불일치에 가까움 |

## 핵심 동작 검증

### [검증 시나리오 1: Workflow 실행 및 이력 저장]

* 입력: `/run` API 호출 또는 `loop` 기반 주기 실행

* 에이전트 동작:

1. 현재 `EnergyState`를 수집하거나 mock state를 생성한다.
2. `run_workflow()`가 `generate → optimize → auction → critique → dispatch`를 수행한다.
3. 최종 전략과 reward, step_events, messages를 생성한다.
4. `persist_workflow_run()`이 episode와 KPI를 DB에 저장한다.
5. strategy memory도 함께 저장된다.

* 실제 결과 요약:

  * selected strategy 생성
  * reward 계산
  * episode/KPI 누적 저장
  * `/episodes`에서 최근 실행 이력 조회 가능

* 실제 응답/산출물 기준 예시:

  * `POST /run` 응답 JSON
  * `GET /episodes`
  * `GET /episodes/{id}`

### [검증 시나리오 2: 정책 검토 및 dispatch 실행]

* 입력: 선택된 전략 + 현재 상태

* 에이전트 동작:

1. `runtime.policy_check()`가 전략의 정책 및 제약 위반 여부를 점검한다.
2. critic 단계에서 위반 후보를 제거하거나 no-strategy로 처리한다.
3. 승인된 전략만 `runtime.dispatch_via_a2a()`로 전달된다.
4. dispatch는 ESS charge/discharge, market quantity, PV curtailment를 실행 record로 변환한다.
5. dispatch log는 이후 KPI 집계와 운영 추적에 활용된다.

* 실제 결과 요약:

  * 정책 위반 후보 차단
  * 승인 전략만 dispatch 수행
  * dry-run/live 구조 유지
  * idempotency 및 power/price 제한 반영

* 실제 응답/산출물 기준 예시:

  * `runtime.dispatch_via_a2a()` action record
  * dispatch log
  * `/kpi` 집계 결과

### [검증 시나리오 3: 자연어 운영 요청 및 memory 활용]

* 입력: `/chat` 요청, 현재 상태 기반 유사 전략 검색

* 에이전트 동작:

1. 운영자가 자연어 요청을 입력한다.
2. `invoke_deep_agent()`가 요청을 처리한다.
3. deep agent 실패 또는 제한 시 workflow fallback으로 응답을 생성한다.
4. `vector_store.search()`가 유사한 과거 전략을 조회할 수 있다.
5. 새 실행 결과는 `vector_store.add_memory()`로 다시 누적된다.

* 실제 결과 요약:

  * 자연어 요청 응답 가능
  * fallback 경로 유지
  * 유사 전략 검색 및 재활용 가능
  * strategy memory가 지속 누적됨

* 실제 응답/산출물 기준 예시:

  * `POST /chat` 응답 JSON
  * strategy memory search result
  * `strategy_memory` DB 레코드

## 요약

현재 시스템의 PoC는 요청하신 원안의 ALFP/CDA/MESA 구조를 그대로 구현한 형태는 아니며, **실제 저장소 기준으로는 AETOS workflow 중심의 운영 최적화 PoC**에 가깝다. 핵심은 다음과 같다.

- 전략 생성, 최적화, 선택, 정책 검토, dispatch가 단계형 workflow로 연결됨
- episode/KPI/history 저장 구조를 통해 운영 결과를 누적 관리함
- strategy memory와 vector search를 통해 과거 전략 재활용이 가능함
- DB, vector, deep agent 장애 시 각각 fallback 경로를 유지함
- API, dashboard, MCP를 통해 운영/조회/연계가 가능한 구조를 갖춤
