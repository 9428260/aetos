### 핵심 사용자 시나리오

**시나리오 1 : 공동주택 에너지 운영 자동 최적화**

* ID : SC-001

* 상황 : 공동주택 단지에서 시간대별 가격, 부하, 태양광 발전량, ESS 상태가 계속 변하는 상황에서 운영자가 별도 수동 판단 없이 최적 운전 전략을 자동 산출하고 실행할 때 사용

* 목표 :

- 단지 전체 reward 최대화
- ESS 충방전, 시장 거래, PV 감발을 통합 최적화
- 운영자의 수동 판단 부담 최소화

* 사전 조건 :

- PostgreSQL 및 이력 저장 기능 정상 동작
- AETOS workflow 실행 가능 상태
- 가격·부하·발전 데이터 수집 또는 시뮬레이션 상태 확보
- 정책 제약값(export limit, SOC min/max) 등록 완료

* 상세 흐름

| 단계 | 사용자 행동 | 시스템 동작 | 비고 |
| ------ | ---------- | ----------------------- | ------ |
| 1 | 운영자가 최적화 실행 또는 스케줄 대기 | 현재 에너지 상태 수집 | API 또는 loop |
| 2 | 별도 입력 없음 | Strategy Agent가 전략 후보 생성 | generate |
| 3 | 별도 입력 없음 | Optimizer Agent가 전략 후보 보정 및 개선 | optimize |
| 4 | 별도 입력 없음 | Auction/Clearing 로직이 후보 간 비교 및 선택 | auction |
| 5 | 결과 확인 | Critic Agent가 정책 위반 여부 검토 | critique |
| 6 | 실행 승인 또는 자동 실행 | Dispatch가 ESS/시장/PV setpoint 생성 | dispatch |
| 7 | 운영 로그 조회 | Episode, KPI, 메시지 이력 저장 | DB 및 history |

* 입력 예시

```csv
timestamp,avg_price,load_kw,generation_kw,ess_soc,export_limit,soc_min,soc_max
2026-06-01T12:00:00Z,0.114,82.5,64.2,0.58,50,0.1,0.9
```

* 기대 출력

```json
{
  "selected_strategy": {
    "mode": "balanced_dispatch",
    "ess_charge": 12.5,
    "ess_discharge": 0.0,
    "market_qty": 18.0,
    "pv_curtailment": 0.0
  },
  "reward": 4.82,
  "status": "Success"
}
```

* 성공 기준

- 기준 1: 운영 이력 저장 성공률 99% 이상
- 기준 2: 전략 실행 자동화율 90% 이상
- 기준 3: 제약 위반 없는 dispatch 유지

**시나리오 2 : ESS 기반 피크 시간 비용 절감 운영**

* ID : SC-002

* 상황 : 피크 시간대에 전력 가격이 상승하고 부하가 증가하는 상황에서 ESS를 활용해 구매 비용을 줄이고 수익성을 높일 때 사용

* 목표

- 피크 시간 전력 구매 최소화
- ESS 활용률 극대화
- 비용 절감과 제약 준수 동시 달성

* 사전 조건

- ESS 상태 데이터 연동 완료
- 요금 또는 가격 데이터 입력 가능
- Forecast/Runtime 또는 시뮬레이션 상태 제공 가능
- Dispatch 제약값 및 idempotency 정책 설정 완료

* 상세 흐름

| 단계 | 사용자 행동 | 시스템 동작 | 비고 |
| ------ | ---------- | ------------ | ------------ |
| 1 | 피크 시간 진입 확인 | 현재 가격 및 부하 상태 반영 | runtime |
| 2 | 운영 실행 | Strategy Agent가 방전 중심 전략 생성 | generate |
| 3 | 별도 입력 없음 | Optimizer가 충방전 비율 조정 | optimize |
| 4 | 자동 선택 | Critic이 SOC/출력/수출 제한 검증 | critique |
| 5 | 실행 승인 | Dispatch가 방전 명령 생성 | dispatch |
| 6 | 결과 조회 | KPI 및 expected reward 집계 | dashboard |

* 입력 예시

```csv
timestamp,ess_id,soc,grid_price,forecast_load_kw,generation_kw
2026-07-15T18:00:00Z,ESS01,0.82,0.185,420,35
```

* 기대 출력

```json
{
  "timestamp": "2026-07-15T18:00:00Z",
  "ess_id": "ESS01",
  "discharge_kw": 180,
  "new_soc": 0.64,
  "cost_saved": 32000,
  "status": "Success"
}
```

* 성공 기준

- 기준 1: 피크 시간 구매 전력 20% 이상 감소
- 기준 2: ESS 활용률 80% 이상
- 기준 3: ESS 제약 위반 0건 유지

**시나리오 3 : 운영 이력 기반 성과 분석 및 재현**

* ID : SC-003

* 상황 : 운영자가 과거 실행 결과를 바탕으로 어떤 전략이 선택되었고 어떤 KPI 성과가 나왔는지 분석하거나 재현하고자 할 때 사용

* 목표

- 운영 이력의 투명한 조회
- 전략 선택 근거 확인
- 향후 운영 품질 개선을 위한 데이터 축적

* 사전 조건

- episode 및 KPI 저장 기능 활성화
- `/episodes`, `/episodes/{id}`, `/kpi` API 정상 동작
- 대시보드 history view 접근 가능
- 로그 및 메시지 저장 활성화

* 상세 흐름

| 단계 | 사용자 행동 | 시스템 동작 | 비고 |
| ------ | ---------- | ---------- | ------ |
| 1 | 이력 조회 화면 접속 | 최근 episode 목록 조회 | history |
| 2 | 특정 실행 선택 | 상세 상태, action, messages 조회 | episode detail |
| 3 | 결과 비교 | reward, cost saving, ESS profit, ROI 표시 | KPI |
| 4 | 원인 분석 | step_events와 agent messages 확인 | explainability |
| 5 | 후속 운영 반영 | 유사 상황 대응 전략 참고 | memory/replay |

* 입력 예시

```json
{
  "episode_id": "5e2dbf4f-54c1-4b2b-8af0-8f2f37d1d2c9"
}
```

* 기대 출력

```json
{
  "id": "5e2dbf4f-54c1-4b2b-8af0-8f2f37d1d2c9",
  "reward": 4.82,
  "cost_saving": 1.44,
  "ess_profit": 1.61,
  "roi": 0.97,
  "messages": ["[generate:a2a] ...", "[dispatch] ..."],
  "status": "Success"
}
```

* 성공 기준

- 기준 1: 최근 실행 이력 조회 성공률 99% 이상
- 기준 2: 선택 전략 및 KPI 재현 가능성 확보
- 기준 3: 운영자가 상세 trace를 1분 내 확인 가능

**시나리오 4 : 자연어 기반 운영 요청 및 질의**

* ID : SC-004

* 상황 : 운영자가 복잡한 파라미터를 직접 입력하지 않고 자연어로 최적화 요청, 상태 질의, 전략 설명을 받고자 할 때 사용

* 목표

- 운영 인터페이스 단순화
- 비기술 사용자 접근성 향상
- 설명 가능한 AI 운영 경험 제공

* 사전 조건

- `/chat` API 활성화
- Deep Agent 설정 완료
- fallback workflow 사용 가능 상태
- 운영 데이터 또는 시뮬레이션 상태 존재

* 상세 흐름

| 단계 | 사용자 행동 | 시스템 동작 | 비고 |
| ------ | ---------- | ---------- | ------ |
| 1 | 자연어 질문 입력 | 입력 메시지 검증 | chat |
| 2 | 실행 요청 | Deep Agent 또는 fallback 호출 | deep agent |
| 3 | 상태 해석 | 현재 운영 문맥과 요청 결합 | prompt/context |
| 4 | 응답 생성 | 최적화 결과 또는 설명 반환 | response |
| 5 | 운영 반영 | 필요 시 `/run` 또는 수동 판단 연결 | ops assist |

* 입력 예시

```text
지금 부하가 높은데 ESS를 활용해서 비용을 최소화하는 전략을 추천해줘
```

* 기대 출력

```json
{
  "reply": "현재 SOC와 가격 수준을 기준으로 피크 시간 방전 중심 전략이 유리합니다. 예상 reward는 4.5 내외이며 export limit은 준수합니다."
}
```

* 성공 기준

- 기준 1: 자연어 요청 응답 성공률 95% 이상
- 기준 2: 운영자가 수동 파라미터 입력 없이 실행 가능
- 기준 3: fallback 포함 안정적 응답 제공

**시나리오 5 : 유사 운영 사례 기반 전략 재활용**

* ID : SC-005

* 상황 : 과거 유사한 가격·부하·발전 조건에서 성과가 좋았던 전략을 참고해 현재 운영 품질을 높이고자 할 때 사용

* 목표

- 과거 우수 전략 재활용
- 초기 전략 탐색 비용 감소
- 운영 품질의 점진적 고도화

* 사전 조건

- vector memory 저장 활성화
- pgvector 또는 메모리 fallback 사용 가능
- strategy memory 누적 데이터 존재
- 검색 top-k 및 embedding 설정 완료

* 상세 흐름

| 단계 | 사용자 행동 | 시스템 동작 | 비고 |
| ------ | ---------- | ---------- | ------ |
| 1 | 최적화 실행 | 현재 state embedding 생성 | vector store |
| 2 | 별도 입력 없음 | 유사 과거 전략 검색 | search |
| 3 | 결과 확인 | score, reward, mode 기반 후보 제시 | memory |
| 4 | 전략 선택 참고 | 현재 후보 생성/보정에 문맥 반영 | strategy assist |
| 5 | 사후 저장 | 신규 episode와 strategy memory 추가 저장 | learning loop |

* 입력 예시

```json
{
  "state": {
    "avg_price": 0.122,
    "avg_load": 88.0,
    "avg_generation": 54.0,
    "ess_soc": 0.61
  },
  "request_text": "peak cost reduction"
}
```

* 기대 출력

```json
{
  "matches": [
    {
      "mode": "peak_shaving",
      "score": 0.93,
      "reward": 5.14
    }
  ],
  "status": "Success"
}
```

* 성공 기준

- 기준 1: 유사 전략 검색 응답시간 2초 이내
- 기준 2: selected memory 활용 사례 누적
- 기준 3: 반복 운영 시 평균 reward 개선

**시나리오 우선순위 매트릭스**

| 시나리오 | 비즈니스 가치 | 구현 난이도 | PoC 포함 |
| ----------- | ---------- | ---------- | ---------- |
| SC-001 (운영 최적화) | 높음 | 중간 | 네 |
| SC-002 (ESS 운영) | 높음 | 중간 | 네 |
| SC-003 (이력 분석) | 높음 | 낮음 | 네 |
| SC-004 (자연어 운영) | 중간 | 중간 | 네 |
| SC-005 (전략 메모리) | 중간 | 높음 | 네 |

**공통 UX 프레임**

**상단 글로벌 바: 날짜·시간 범위, 실시간 실행 토글, 시나리오 선택(실시간/샌드박스), 알림센터, 프로필·권한, 검색**

**좌측 내비게이션: 대시보드 / 전략 실행 / 이력 조회 / KPI / 로그 / 설정**

* 핵심 위젯 패턴

  * KPI 카드: reward, cost saving, ESS profit, ROI, 성공률
  * 시계열 차트: 가격·부하·발전·ESS SOC 추이
  * 전략 비교 패널: 후보 전략별 mode, bid, market qty, ESS charge/discharge
  * 실행 로그 패널: generate, optimize, auction, critique, dispatch 이벤트
  * 히스토리 테이블: episode 목록, timestamp, reward, mode, KPI

* 공통 기능

  * “왜 이 결정인가” 설명: step_events, critic 결과, messages 기반 설명
  * 샌드박스 실행: mock state 기반 시뮬레이션
  * 정책 변경 이력 및 설정 반영 여부 확인
  * 로그/이력 조회와 KPI 연계 분석
  * API 및 MCP 연계를 위한 운영 인터페이스 확장

* 접근성/모바일

  * 모바일: KPI, 최근 실행 결과, 경고 알림 중심
  * 데스크톱: 전략 후보 비교, 이력 분석, 상세 trace 중심

**1) Strategy Agent**

* 대시보드

  * KPI: 생성 전략 수, 선택률, 평균 reward 기여도
  * 실시간 상태 기반 전략 후보 목록 표시

* 전략·시뮬레이션

  * 현재 상태 기준 운영 모드 비교
  * 공격형/균형형/보수형 전략 후보 비교

* 알림

  * 전략 후보 부족
  * 비정상 reward 예상
  * 상태 입력 이상

**2) Optimizer Agent**

* 대시보드

  * KPI: 평균 개선율, 최적화 시간, 후보 유지율
  * 전략 개선 전후 성능 비교

* 전략·시뮬레이션

  * bid, ESS rate, PV curtailment, market quantity 조정
  * 후보별 개선 폭 표시

* 알림

  * 개선 실패
  * 최적화 편차 과다
  * 입력 state 이상

**3) Critic Agent**

* 대시보드

  * KPI: 필터링 건수, 제약 위반 차단율, 정책 준수율
  * 위반 유형 분포 표시

* 정책 검토

  * export limit, SOC 범위, 운영 제약 검증
  * 위반 전략 제외 사유 설명

* 알림

  * 제약 위반 후보 다수 발생
  * 선택 가능한 전략 부족
  * 정책 설정 누락

**4) Dispatch Agent**

* 대시보드

  * KPI: 실행 성공률, 마지막 실행 시각, ESS charge/discharge 총량
  * 최근 dispatch 명령 로그

* 운영

  * 실시간 setpoint 생성
  * dry-run / live 모드 구분
  * idempotency key 기반 중복 방지

* 알림

  * dispatch 실패
  * 출력 한계 초과 위험
  * 중복 실행 감지

**5) Deep Agent**

* 대시보드

  * KPI: 자연어 요청 수, 성공률, fallback 비율
  * 최근 요청/응답 이력

* 운영

  * 운영 질의응답
  * 전략 설명
  * 자연어 기반 최적화 요청 처리

* 알림

  * rate limit 접근
  * 설정 오류
  * deep agent fallback 발생

**6) Forecast Runtime**

* 대시보드

  * KPI: 예측 호출 수, 평균 응답시간, 입력 품질
  * 가격·부하·발전 예측 결과 표시

* 모델 운영

  * 현재는 runtime 기반 예측/시뮬레이션 제공
  * 향후 외부 예측 모델 연동 가능 구조

* 알림

  * 데이터 결측
  * 예측 입력 이상
  * 외부 연동 실패

**7) Memory Layer**

* 대시보드

  * KPI: memory 저장 건수, selected strategy 비율, 검색 성공률
  * 최근 유사 전략 목록

* 운영

  * state + strategy 기반 벡터 저장
  * 유사 전략 검색
  * 과거 성과 기반 의사결정 보조

* 알림

  * pgvector 미사용 fallback 전환
  * memory 저장 실패
  * 검색 결과 부족

**공통 리포트/운영 뷰**

* 일일 운영 브리핑: 총 실행 횟수, 평균 reward, KPI 합계, 실패 이벤트 요약
* 이벤트 타임라인: generate, optimize, critique, dispatch, history 저장 순서 표시
* 샌드박스 vs 실제 실행 구분 배지
* 재현 가능한 episode ID, timestamp, selected mode, reward 메타데이터 제공

**권한/보안**

* 역할: Admin / Energy Ops / Analyst / Auditor / Viewer
* 뷰 단위 권한: 실행과 설정 변경은 승인 권한 필요
* 이력 및 로그는 감사 추적 유지
* 사용자 식별 데이터는 최소화하고 운영 중심 데이터 위주로 처리

**실시간성/성능 가이드**

* 업데이트 간격: 실행 로그 1~5초, KPI/이력 조회 수초~수분, 배치 리포트 일 1회
* 오프라인 모드: 핵심 이력 조회와 경고 확인 중심
* 성능 목표: 전략 선택 5초 이내, 이력 조회 1초 이내, 자연어 응답은 fallback 포함 안정성 우선
