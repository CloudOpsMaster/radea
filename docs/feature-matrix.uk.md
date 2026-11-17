# Матриця «стаття → функція → реалізація RADEA»

Охоплено всі **60 наявних статей №21–80**. Статті №1–20 у наданій папці відсутні.
Статті використовуються як вимоги й принципи; їхній локальний корпус та ілюстрації
не публікуються разом із продуктом.

- **Покрито в scope**: відповідний контракт RADEA реалізовано й перевіряється тестами.
- **Частково**: є конкретна реалізація, але вона не охоплює весь сценарій статті.
- **Узгоджено**: принцип відповідає архітектурі, окремої функції не потребує.
- **Поза scope**: такої можливості немає; вона не є прихованою обіцянкою продукту.

| № | Стаття | Функція / принцип | Що зроблено | Статус | Межа реалізації |
|---|---|---|---|---|---|
| 21 | Migrating CI/CD Between Platforms: Lessons Learned | Інвентаризація, переклад семантики, shadow run | GitHub adapters; інші vendor templates experimental | Частково | Мігратора й semantic diff немає. |
| 22 | Reverse-Engineering Legacy Pipelines with AI | Розбір залежностей і перевірка гіпотез | debug, evidence IDs, перевірка цитат, head/tail логів | Частково | Граф pipeline і characterization legacy поведінки не реалізовані. |
| 23 | Monorepo vs. Polyrepo in the Age of AI Tooling | Контекст та явні контракти між компонентами | Модульні контракти, Python facade та Protocol для моделі | Частково | Cross-repo retrieval та impact analysis немає. |
| 24 | Modernizing Shell Scripts with AI (Carefully) | Безпечне переписування та ShellCheck | AI не виконує запропоновані команди | Поза scope | Shell-review команди та порівняння before/after немає. |
| 25 | Documentation Debt: Fixing It as a Side Effect of AI | Документація поруч із кодом | README, architecture, integration, threat model, feature matrix | Покрито в scope | Документація описує перевірену поведінку та межі. |
| 26 | Config Translation: Moving Between Tools with AI | Переклад із semantic validation | Версіонований API інтеграції; незалежна перевірка plan facts | Поза scope | Конвертера між конфігураційними форматами немає. |
| 27 | Strangler-Fig Migrations Guided by AI | Facade, incremental cutover, shadow comparison | Facade використано для інтеграції самого CLI | Поза scope | Це не migration facade для чужих production-систем. |
| 28 | From Snowflake Servers to Reproducible Infra | Discovery і rebuild із IaC | Локальний аналіз Terraform-плану | Частково | Discovery серверів і перевірка rebuild equivalence відсутні. |
| 29 | Zero-Downtime Cutovers: Planning with AI Assistance | Планування forward/rollback і rehearsal | Автоматичних cutover/deploy операцій немає | Поза scope | Runbook generation і rehearsal не реалізовані. |
| 30 | When NOT to Modernize: A Pragmatic Checklist | Вузькі зміни за конкретною потребою | Вузький advisory CLI; відділені адаптери й правила | Узгоджено | Це архітектурний принцип, не окрема команда. |
| 31 | DevSecOps Meets AI: Shifting Security Left, Practically | AI пояснює; код застосовує hard gates | policy-check; локальні IAM правила; required CI, pip-audit, Bandit | Покрито в scope | Не замінює організаційний policy engine. |
| 32 | Never Paste Secrets: Safe Prompting for Engineers | Redaction-first і мінімізація даних | Очищення input/output, PII placeholders, bounded context, dry-run | Покрито в scope | Best effort; не гарантія універсального DLP. |
| 33 | Reviewing AI-Generated IAM/RBAC Before It Bites You | Least privilege і незалежні аналізатори | Локальний детектор literal Action/Resource wildcard із evidence | Частково | Не аналізує effective permissions, trust graph або Kubernetes RBAC. |
| 34 | Dependency and Supply-Chain Risk with AI Assistance | Pin/hash, перевірка походження, SBOM | uv.lock, hashed exports, SHA-pinned Actions, SBOM і provenance workflow | Покрито в scope | Хмарні model aliases залишаються provider-controlled. |
| 35 | Threat Modeling with AI as a Brainstorming Partner | Trust boundaries і STRIDE brainstorming | Threat model самого RADEA; негативні security fixtures | Частково | Немає користувацької STRIDE-команди чи backlog workflow. |
| 36 | Securing the AI Tools in Your Own Pipeline | Least privilege, isolation, audit | Fail-closed routing, endpoint policy, Kiro env/tools, audit, fork isolation | Частково | OS sandbox та network egress керуються раннером. |
| 37 | SBOMs, Vulnerabilities, and AI Triage | Інвентар і детерміновані CVE checks | CycloneDX runtime dependency SBOM і blocking pip-audit у CI | Частково | AI reachability/dedup/CVE triage як функції продукту немає. |
| 38 | Secrets Management: The Hardest Part of Every Migration | Не передавати й не зберігати секретні значення | Redaction, metadata-only audit, credential-safe errors і comments | Частково | Ротація, Vault і карта consumers не реалізовані. |
| 39 | Policy-as-Code Explained and Drafted by AI | Versioned deterministic allow/deny | policy-check з explicit exception; complete-plan check; allow/deny тести | Покрито в scope | Правила вузькі, не універсальний OPA/Rego engine. |
| 40 | The Security Risks of Trusting AI Output Blindly | Draft + незалежна перевірка | Schema/evidence checks, verified=false, локальні факти не підміняються LLM | Покрито в scope | Причинність і коректність висновків перевіряє людина. |
| 41 | Platform Engineering: Paving the Golden Path with AI | Validated opinionated workflow | Python API, CLI, hashed install, перевірені GitHub adapter contracts | Частково | Scaffolding сервісів, drift summaries та adoption feedback відсутні. |
| 42 | Internal Developer Platforms and the AI Help Desk | Retrieval, citations, human escalation | Є evidence на надані файли | Поза scope | Немає knowledge-base retrieval або help-desk workflow. |
| 43 | Incident Management: Drafting Postmortems with AI | Доказова timeline; людський root cause | triage з evidence IDs/quotes, unverified cause, human conclusion/actions fields | Частково | Blamelessness підтримує prompt; фінальне авторство й публікація людські. |
| 44 | On-Call in the AI Era: Less Toil, Same Responsibility | Observe, correlate, draft; не remediatе | triage та порівняння явно наданих baseline/current metrics | Частково | Runbook retrieval, alert ingestion і remediation не реалізовані. |
| 45 | Building an AI Adoption Playbook for Your Team | Pilot, guardrails, вимірювання користі | Evaluation guide, synthetic cases, offline scorer recorded outputs | Частково | Потрібен human-scored pilot на реальних знеособлених даних. |
| 46 | The Verification Mindset: The Core Skill of the AI Era | Run/test/trace/cross-check | Регресії на реальні прогалини, SDK/process contracts, wheel smoke, required CI | Покрито в scope | Unit tests не сертифікують якість діагнозів живих моделей. |
| 47 | Prompt Engineering for Infrastructure Work | Контекст, формат, constraints, assumptions | Версіоновані prompts, evidence budget, schema та provenance hashes | Частково | Немає автоматичного retrieval версій провайдерів і документації. |
| 48 | Will AI Replace DevOps Engineers? An Honest Answer | Механіка для AI, рішення для інженера | Advisory analysis; жодних apply/deploy/merge від моделі | Узгоджено | Людина зберігає відповідальність за рішення. |
| 49 | Learning DevOps Faster with AI as a Tutor | Пояснення з перевіркою розуміння | Перевірювані посилання на вхідні дані й review surface | Поза scope | Tutor/quiz/learning mode не реалізований. |
| 50 | The 1.3x Engineer: A Realistic View of AI Productivity | Вимірювати сумарну користь із review overhead | Evaluation protocol; жодних вигаданих 1.3x/MTTR claims | Частково | Реальні вимірювання ще не проведені. |
| 51 | Kubernetes Deployment Strategies: Rolling, Blue-Green, Canary | Rolling / blue-green / canary | Kubernetes/Helm runtime не реалізовано | Поза scope | Це Python CLI; додавати кластерний механізм для цих use cases не потрібно. |
| 52 | Rolling Updates in Kubernetes: Mechanics, Pitfalls, and Tuning | Surge, availability і version skew | Kubernetes/Helm runtime не реалізовано | Поза scope | Це Python CLI; додавати кластерний механізм для цих use cases не потрібно. |
| 53 | Blue-Green Deployments on Kubernetes Done Right | Preview environment і cutover | Kubernetes/Helm runtime не реалізовано | Поза scope | Це Python CLI; додавати кластерний механізм для цих use cases не потрібно. |
| 54 | Canary Releases and Progressive Delivery in Kubernetes | Traffic split, bake windows і abort | Kubernetes/Helm runtime не реалізовано | Поза scope | Це Python CLI; додавати кластерний механізм для цих use cases не потрібно. |
| 55 | GitOps: The Declarative Deployment Model for Kubernetes | Pull/reconcile і reviewed promotion | Kubernetes/Helm runtime не реалізовано | Поза scope | Це Python CLI; додавати кластерний механізм для цих use cases не потрібно. |
| 56 | Health Probes: Readiness, Liveness, and Startup Explained | Readiness/liveness/startup validation | Kubernetes/Helm runtime не реалізовано | Поза scope | Це Python CLI; додавати кластерний механізм для цих use cases не потрібно. |
| 57 | Achieving Zero-Downtime Deployments on Kubernetes | Graceful shutdown і PDB | Kubernetes/Helm runtime не реалізовано | Поза scope | Це Python CLI; додавати кластерний механізм для цих use cases не потрібно. |
| 58 | Rollbacks and Release Safety in Kubernetes | Перевірені immutable artifacts | Перевірений wheel просувається без повторної збірки | Частково | Kubernetes rollback/rehearsal немає. |
| 59 | Deployment vs StatefulSet vs DaemonSet: Choosing the Right Workload | Deployment / StatefulSet / DaemonSet | Kubernetes/Helm runtime не реалізовано | Поза scope | Це Python CLI; додавати кластерний механізм для цих use cases не потрібно. |
| 60 | Feature Flags and Kubernetes: Decoupling Deploy from Release | Deploy окремо від release | Kubernetes/Helm runtime не реалізовано | Поза scope | Це Python CLI; додавати кластерний механізм для цих use cases не потрібно. |
| 61 | Helm Charts Fundamentals: Templating Kubernetes the Right Way | Render/lint і values precedence | Kubernetes/Helm runtime не реалізовано | Поза scope | Це Python CLI; додавати кластерний механізм для цих use cases не потрібно. |
| 62 | Helm Chart Best Practices for Production | Рання schema validation | Схеми результатів перевіряються до presentation/posting | Частково | Helm charts, probes та manifest policy відсутні. |
| 63 | Managing Values and Environments with Helm | Overlays і secrets references | Kubernetes/Helm runtime не реалізовано | Поза scope | Це Python CLI; додавати кластерний механізм для цих use cases не потрібно. |
| 64 | Helm vs Kustomize: Choosing a Manifest Strategy | Manifest generation strategy | Kubernetes/Helm runtime не реалізовано | Поза scope | Це Python CLI; додавати кластерний механізм для цих use cases не потрібно. |
| 65 | Building Container Images: Best Practices for Kubernetes Apps | Scan та SBOM перед доставкою | Є scanning/SBOM Python dependencies, wheel smoke | Частково | Docker image не постачається; container hardening не заявляється. |
| 66 | Multi-Stage Docker Builds for Lean, Secure Images | Відокремити builder від runtime | Kubernetes/Helm runtime не реалізовано | Поза scope | Це Python CLI; додавати кластерний механізм для цих use cases не потрібно. |
| 67 | From Source Code to a Running Pod: The Full Build Pipeline | Test перед публікацією артефакту | Спільний CI, hashes, wheel/sdist validation і artifact promotion | Частково | Image registry і deploy-to-pod pipeline немає. |
| 68 | ConfigMaps and Secrets: Configuring Applications in Kubernetes | Конфігурація окремо від credentials | Config із env, секрети не входять в AnalysisRequest/repr/audit | Частково | Kubernetes Secret mounts та external-secrets operator відсутні. |
| 69 | Image Tagging, Digests, and Supply-Chain Integrity | Перевірене походження артефакту | SHA-pinned tooling, checksums, SBOM і release attestation workflow | Частково | Не реалізовано image signing/admission policy. |
| 70 | The Helm Release Lifecycle: Install, Upgrade, Rollback | Install/upgrade/rollback history | Kubernetes/Helm runtime не реалізовано | Поза scope | Це Python CLI; додавати кластерний механізм для цих use cases не потрібно. |
| 71 | Custom Resource Definitions (CRDs) Explained | API schema та versioning | Kubernetes/Helm runtime не реалізовано | Поза scope | Це Python CLI; додавати кластерний механізм для цих use cases не потрібно. |
| 72 | The Kubernetes Operator Pattern: Automating Operations | Idempotent reconciliation | Kubernetes/Helm runtime не реалізовано | Поза scope | Це Python CLI; додавати кластерний механізм для цих use cases не потрібно. |
| 73 | Building Your First Kubernetes Operator: Concepts and Flow | Spec/status, finalizers, backoff | Kubernetes/Helm runtime не реалізовано | Поза scope | Це Python CLI; додавати кластерний механізм для цих use cases не потрібно. |
| 74 | Testing Applications on Kubernetes: A Layered Strategy | Швидкі тести й наскрізні контракти | Unit, public API, SDK/process, GitHub flow, installed-wheel smoke | Частково | Kubernetes manifest/probe tests не застосовуються до CLI. |
| 75 | Integration Testing Inside Kubernetes Clusters | Перевірка зовнішніх меж | Є SDK/process і GitHub adapter contracts | Поза scope | Реального кластера та neighbors для цього CLI немає. |
| 76 | End-to-End Testing with Ephemeral Kubernetes Environments | Ізоляція, fixtures і teardown | Temporary directories, isolated audit env, separate wheel venv | Частково | Це ізоляція CLI-тестів, не PR Kubernetes environment. |
| 77 | Autoscaling in Kubernetes: HPA, VPA, and Cluster Autoscaler | HPA/VPA/Cluster Autoscaler | Kubernetes/Helm runtime не реалізовано | Поза scope | Це Python CLI; додавати кластерний механізм для цих use cases не потрібно. |
| 78 | Resource Requests and Limits: Getting Them Right | Обмежене споживання ресурсів | Streaming sources, byte/line/file/context/output limits, bounded aliases | Частково | HPA/VPA/resource quotas та production sizing benchmark не реалізовані. |
| 79 | Observability for Kubernetes Applications: Logs, Metrics, Traces | Logs/metrics/traces correlation | Logs із evidence IDs, локальні числові deltas, приватні audit metadata | Частково | Traces ingestion і correlation за trace ID не реалізовані. |
| 80 | Debugging Kubernetes Workloads in Production Safely | Observe first і audit trail | Read-only advisory analysis, source evidence, metadata audit | Частково | Немає kubectl collector, ephemeral debug containers або rollout operations. |

## Де перевірити реалізацію

| Функція | Код | Перевірка |
|---|---|---|
| Public API / service layer | [api.py](../src/radea/api.py), [service.py](../src/radea/core/service.py), [models.py](../src/radea/core/models.py) | [test_api.py](../tests/test_api.py) |
| Redaction / bounded evidence | [sanitizer.py](../src/radea/core/sanitizer.py), [sources.py](../src/radea/core/sources.py) | [test_guardrails.py](../tests/test_guardrails.py) |
| Schema / draft / provenance | [contracts.py](../src/radea/core/contracts.py), [runtime.py](../src/radea/core/runtime.py), [results.py](../src/radea/core/results.py) | Bad quotes/IDs, spoofing, malformed output fixtures |
| Terraform facts / policy | [plan.py](../src/radea/iac_review/plan.py), [policy.py](../src/radea/iac_review/policy.py) | Delete/replace без LLM; allow/deny cases |
| Metrics / audit | [metrics.py](../src/radea/incident_triage/metrics.py), [audit.py](../src/radea/core/audit.py) | Deltas, zero baseline, private permissions, failed/symlink audit |
| GitHub integration | [github.py](../src/radea/integrations/github.py), [comment.py](../src/radea/notify/comment.py) | [test_integrations.py](../tests/test_integrations.py) |
| Reproducible delivery | [CI](../.github/workflows/ci.yml), [Release](../.github/workflows/release.yml) | [test_delivery.py](../tests/test_delivery.py), actual GitHub checks |

[Архітектура й Python API](architecture.md) · [CI інтеграція](ci-integration.md) ·
[Threat model](threat-model.md) · [Оцінка якості й pilot](evaluation.md) · [Живі acceptance-перевірки](acceptance.md).

Живі backend-и не сертифіковані цією таблицею. Уніфікований контракт і моковані
SDK/process перевірки не замінюють live smoke вашої версії Kiro та human-scored pilot.

Оновлення offline default: усі три команди формують локальні чернетки без моделі.
Експериментальні linear/MLP класифікатори дають лише категорійну підказку для debug.
[Порівняння та межі набору даних](offline.md); це не підтвердження виробничої точності.
