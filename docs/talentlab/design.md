**Agent 페르소나 및 시스템 프롬프트 (Identity)**

| 항목 | 정의 내용 |
| --- | --- |
| Agent 이름 | `Strategy Agent`, `Optimizer Agent`, `Critic Agent`, `Dispatch Agent`, `Deep Agent`, `Memory Layer` |
| 주요 역할 | 가격·부하·발전·ESS 상태를 바탕으로 운영 전략을 생성하고, 이를 검증한 뒤 ESS 운전, 시장 거래, PV 감발, 자연어 운영 요청 처리, 실행 이력 저장까지 연결하는 멀티에이전트 운영 시스템 |
| 핵심 목표 | 실행 가능한 의사결정 생성, reward 최대화, 정책 및 물리 제약 위반 방지, 운영 이력 및 KPI 축적, 유사 전략 재활용 |
| 톤앤매너 | 규칙 기반·운영 지향·보수적 판단 중심. 설명형 출력보다 구조화된 결과와 실행 가능한 결정 우선 |
| 제약 사항 | 정책 위반 액션 승인 금지, ESS/시장/감발 한계 초과 금지, 검증 실패 시 재선정 또는 차단, DB 실패 시 memory-only fallback, vector search 실패 시 in-memory fallback |

시스템 프롬프트 관점에서 보면 각 에이전트는 “자유 대화형 비서”가 아니라 “역할이 고정된 운영 에이전트”에 가깝습니다. 예를 들어 `Strategy Agent`는 전략 후보 생성, `Optimizer Agent`는 후보 개선, `Critic Agent`는 제약 검증, `Dispatch Agent`는 실행 명령 변환, `Deep Agent`는 자연어 요청 처리, `Memory Layer`는 전략 기억과 재사용을 담당하는 식으로 역할이 분리되어 있습니다.

**워크플로우 및 오케스트레이션 (Workflow & Logic)**

**2.1 처리 로직**

* Step 1 (Input Analysis): 현재 시스템은 `EnergyState`를 기준 입력으로 사용하며, 가격 배열, 부하 배열, 발전량 배열, `ess_soc`, 제약조건, timestamp를 받아 실행 범위를 결정한다.

* Step 2 (Tool Selection): workflow 구간에서는 전략 생성, 최적화, 경매/선택, 정책 검토, dispatch 단계를 수행하고, 자연어 요청 시에는 `Deep Agent` 또는 fallback workflow를 사용한다. 실행 이후에는 persistence 계층에서 episode, KPI, strategy memory를 저장한다.

* Step 3 (Execution & Response): 승인된 전략만 dispatch에 반영하고, 실행 결과를 reward 및 KPI로 평가한 뒤 JSON 응답, 로그, 메시지, 이력, 메모리로 저장한다.

**2.2 상태 관리**

* 상태 정의: 현재 구현은 별도 `ALFPState` 대신 `EnergyState`와 workflow result dict를 사용한다. 주요 상태는 `price`, `load`, `generation`, `ess_soc`, `constraints`, `timestamp`, `step_events`, `optimized`, `selected`, `reward`, `reward_decomposition`, `messages` 등이다.

* Workflow 흐름: `generate → optimize → auction → critique → dispatch`

* 조건 분기: 적합한 전략이 없거나 critic 단계에서 위반이 발생하면 후보를 제외하거나 `no strategy` 상태로 종료한다.

* 거버넌스 흐름: `selected strategy → critic validation → dispatch decision`

* 종료 분기: 실행 후 결과에 따라 `persist_workflow_run`, `vector_store.add_memory`, API 응답 또는 memory fallback으로 이동한다.

* 후속 파이프라인: workflow 이후 `episode 저장 → KPI 집계 → strategy memory 저장 → dashboard/API 조회` 순으로 이어진다.

**도구(Tools) 및 함수 명세 (Capability)**

| 도구명 (Function Name) | 기능 설명 (Description) | 입력 파라미터 (Input Schema) | 출력 데이터 (Output) |
| --- | --- | --- | --- |
| `run_workflow` | AETOS 전체 의사결정 workflow 실행 | `state: EnergyState` | 최종 `result dict` |
| `persist_workflow_run` | episode 및 KPI 저장 | `state`, `result`, `source: "api" \| "loop"` | `episode_id` |
| `invoke_deep_agent` | 자연어 운영 요청 처리 | `message: str` | `reply: str` |
| `runtime.forecast` | 가격·부하·발전 예측값 생성 | `horizon: int` | forecast dict |
| `runtime.optimize_via_a2a` | A2A 기반 최적화 실행 | `state: EnergyState` | selected strategy/result |
| `runtime.policy_check` | 전략의 정책·제약 검증 | `strategy`, `state` | compliance result |
| `runtime.dispatch_via_a2a` | 승인된 전략의 dispatch 실행 | `strategy`, `state`, `dry_run`, `idempotency_key?` | action record |
| `runtime.kpi` | 최근 KPI 집계 반환 | 없음 | KPI dict |
| `vector_store.add_memory` | 전략 메모리 저장 | `episode_id`, `source`, `state`, `strategy`, `reward`, `selected` | 없음 |
| `vector_store.search` | 유사 전략 검색 | `state`, `request_text`, `top_k`, `selected_only` | match list |

**지식 베이스 및 메모리 전략 (Context & Memory)**

**4.1 RAG (검색 증강 생성) 전략**

* 참조 데이터 소스: 현재 구현 기준으로는 문서형 RAG보다 실행 데이터와 DB 메모리 중심이다. 주요 참조 소스는 `episodes`, `kpi`, `strategy_memory`, workflow `messages`, `step_events`, dispatch log이다.

* 청킹(Chunking) 방식: 문서 청킹 구조는 없고, 전략/상태 단위의 레코드 저장 구조를 사용한다.

* 임베딩 모델: Azure OpenAI embedding이 설정된 경우 사용하고, 미설정 시 수치형 fallback embedding을 사용한다.

* Vector DB: PostgreSQL `pgvector` 기반 `strategy_memory` 테이블을 사용하며, 실패 시 in-memory cosine search로 fallback한다.

현재 시스템은 전형적인 문서형 RAG보다는 “이전 실행 상태 + 전략 성과 기록 + step trace”를 재사용하는 메모리 기반 구조다. 따라서 “비문서형 실행 메모리 중심 아키텍처”로 보는 것이 정확하다.

**4.2 대화 메모리 (Conversation History)**

* 메모리 유형: 세션 대화 메모리보다 실행 단위 상태 메모리와 런 간 persistent strategy memory를 사용한다.

* 저장 전략: `episodes`에 실행 요약과 trace를 저장하고, `kpi`에 성과를 저장하며, `strategy_memory`에 전략/상태/보상/embedding을 append 형태로 축적한다. API 장애 시에는 `_mem_episodes`를 임시 메모리로 사용한다.

* 초기화 기준: 대화 턴 기준 초기화는 없고, 실행 런 단위로 새 상태를 만들되 과거 episode와 strategy memory는 누적 유지한다.

**핵심 에이전트 기술 스택**

| 구분 | 선정 전략/기술 | 선정 사유 (논리적 근거) |
| --- | --- | --- |
| LLM Model | 선택적 LLM 사용 구조, 기본적으로 workflow fallback 가능 | 운영 파이프라인에서 안정성과 재현성이 중요하므로 LLM 의존도를 강제하지 않고, 자연어 요청과 일부 설명 단계에 한해 선택적으로 사용 |
| Agent Framework | 자체 workflow + A2A 구조 + Deep Agent 연계 | 현재 시스템은 단계형 workflow와 역할 분리 구조가 명확하며, API와 loop 양쪽에서 재사용 가능함 |
| Prompt Strategy | Role-based Prompt + Rule-based Validation + fallback workflow | 각 에이전트가 역할이 분명하고 실제 실행 결정은 제약 검증이 필요하므로 자유 추론보다 역할 고정형 구조가 적합 |
| Output Parsing | Structured dict/JSON 중심 | `dispatch`, `episodes`, `kpi`, API 응답, DB 저장과 연동하려면 정형 출력이 필수 |
| Monitoring | Console 로그, API 로그, episode history, KPI 집계, step_events, vector memory 로그 | 전략 생성, 검증, 실행, 저장 단계의 추적 포인트가 다르기 때문에 다층 로깅 구조가 실제 운영과 디버깅에 유리 |
