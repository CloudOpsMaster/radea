# Матриця «стаття → функція → реалізація RADEA»

Охоплено всі **80 статей** серії (№1–50 про AI у DevOps, №51–80 про Kubernetes, Helm і образи).
Статті використовуються як вимоги й принципи; їхній локальний корпус та ілюстрації не
публікуються разом із продуктом. Правила детермінованих перевірок посилаються на номери статей
у [довіднику правил](rules.md), і тест перевіряє, що кожне правило має джерело.

- **Покрито в scope**: відповідний контракт RADEA реалізовано й перевіряється тестами.
- **Частково**: є конкретна реалізація, але вона не охоплює весь сценарій статті.
- **Узгоджено**: принцип відповідає архітектурі, окремої функції не потребує.
- **Поза scope**: такої можливості немає; вона не є прихованою обіцянкою продукту.

Підсумок: покрито в scope — 22, частково — 34, узгоджено — 5, поза scope — 19.

| № | Стаття | Функція / принцип | Що зроблено | Статус | Межа реалізації |
|---|---|---|---|---|---|
| 1 | Why AI Belongs in Your CI/CD Pipeline | Помічник, а не автопілот | Чернетки з `draft: true`; людина вирішує; офлайн за замовчуванням | Узгоджено | Окупність і час нагляду не вимірюються. |
| 2 | Debugging Failing Builds with AI | `debug` | 36 локальних сигнатур, класифікація, ранжовані гіпотези з evidence ID і кроком перевірки | Покрито в scope | Сигнатури — сигнал, не доведена причина; невідомі помилки лишаються `unknown`. |
| 3 | Generating and Maintaining Tests with AI in CI | Генерація тестів | — | Поза scope | Тести не генеруються; `flaky` лише аналізує результати. |
| 4 | AI-Assisted Code Review | Рев'ю коду | — | Поза scope | Перевіряються конфігурації, не вихідний код застосунків. |
| 5 | Taming CI/CD YAML with AI | `ci-review` | GitHub Actions і GitLab CI: pin, привілейовані тригери, ін'єкції, curl-to-shell, секрети, `!reference` | Покрито в scope | Схема платформи не валідується повністю; використовуйте `glab ci lint` / `actionlint` разом. |
| 6 | Flaky Tests: Using AI to Find the Root Cause | `flaky` | Аналіз багатьох JUnit-запусків: flaky проти постійно зламаних, підказка механізму, flips | Покрито в scope | Підказка з повідомлень, не діагноз; карантин і loop-запуски не виконуються. |
| 7 | Shortening the Feedback Loop with AI | Час до діагнозу | `debug` і `triage` скорочують читання логів | Частково | Тривалість пайплайна, кеш і паралелізм не вимірюються. |
| 8 | AI for Release Notes and Changelog Automation | `changelog` | Технічний changelog і чернетка release notes з git, звіт про гігієну комітів, позначка DRAFT | Покрито в scope | Публікація не виконується; формулювання перевіряє людина. |
| 9 | Pipeline Observability: Letting AI Read Build Logs | `triage` | Патерни, часова шкала, числові дельти метрик | Частково | Немає регулярної агрегації й сповіщень. |
| 10 | Measuring the ROI of AI in Your Delivery Pipeline | Метрики ефекту | Приватний аудит-лог метаданих (команда, час, статус) | Частково | DORA-метрик і базової лінії немає. |
| 11 | AI as a Co-Pilot for Infrastructure-as-Code | `tf-review`, `iac-review`, `policy-check` | Перевірка Terraform до плану, правила на destroy/replace | Частково | Генерація й рефакторинг IaC не виконуються. |
| 12 | Auditing Dockerfiles with AI | `dockerfile-review` | Root, mutable теги, секрети в шарах, remote-скрипти, гігієна пакетів | Покрито в scope | CVE-сканер окремо; `vuln-triage` читає його звіти. |
| 13 | Debugging Kubernetes with AI | `debug` | Сигнатури ImagePullBackOff, CrashLoop, Scheduling, Eviction, OOM/137, RBAC, probes, Helm | Частково | Читає наданий вивід; `kubectl` не викликається, runbook не створюється. |
| 14 | Right-Sizing Kubernetes Workloads with AI | `rightsize` | Перцентилі p95/p99/max з запасом, пояснення виведення, RS001–RS004 | Покрито в scope | Збір метрик і застосування змін не виконуються; валідація в staging — за людиною. |
| 15 | AI-Assisted Helm Chart Refactoring | Перевірки чарта | HELM001–HELM009 для джерела чарта | Частково | Рефакторинг і diff відрендерених маніфестів немає. |
| 16 | Terraform at Scale: Where AI Helps and Where It Hurts | `policy-check`, `tf-review` | Блокуючий gate на delete/replace, pin версій, захисні механізми | Покрито в scope | Стан і дрейф не бачить; значення з variables не обчислює. |
| 17 | Cloud Cost Optimization with AI | Over-provisioning | RS004 для завищених requests | Частково | Біллінг, атрибуція й аномалії вартості відсутні. |
| 18 | AIOps: Turning 10,000 Log Lines into One Insight | `triage` | Патерни з evidence-посиланнями, санітизація до обробки | Покрито в scope | Кластеризація за правилами, без статистичних моделей. |
| 19 | Anomaly Detection for Metrics | `triage --metrics` | Числові дельти до baseline, нульові baseline як `null` | Частково | Адаптивного baseline, shadow mode й зворотного зв'язку немає. |
| 20 | Self-Healing Infrastructure: Hype vs. Reality | Автовиправлення | Свідомо відсутнє: інструмент нічого не виконує | Поза scope | Лише рекомендації. |
| 21 | Migrating CI/CD Between Platforms | Перевірка результату міграції | `ci-review` перевіряє перенесені пайплайни | Частково | Мігратора, shadow-run і semantic diff немає. |
| 22 | Reverse-Engineering Legacy Pipelines | Розбір пайплайнів | Evidence IDs, `ci-review`, перевірка цитат | Частково | Графа залежностей і characterization-тестів немає. |
| 23 | Monorepo vs. Polyrepo | Контекст і контракти | Модульні контракти, Python facade | Частково | Cross-repo аналізу немає. |
| 24 | Modernizing Shell Scripts with AI | Shell у CI | CI005/CI006 перевіряють shell-фрагменти пайплайнів | Частково | Окремого shell-linter і before/after порівняння немає. |
| 25 | Documentation Debt | Документація поряд із кодом | README, docs, `rules.md` генерується з каталогу і перевіряється тестом | Узгоджено | Автогенерації решти документації немає. |
| 26 | Config Translation Between Tools | Переклад конфігурацій | — | Поза scope | Конвертера немає. |
| 27 | Strangler-Fig Migrations | Міграційний фасад | — | Поза scope | Це не інструмент міграції чужих систем. |
| 28 | From Snowflake Servers to Reproducible Infra | Відтворюваність | `tf-review` перевіряє записану інфраструктуру | Частково | Discovery серверів і перевірка rebuild відсутні. |
| 29 | Zero-Downtime Cutovers | Планування cutover | K8S013–K8S019 перевіряють основи безвідмовного розгортання | Частково | Runbook і rehearsal не генеруються. |
| 30 | When NOT to Modernize | Стриманість | Інструмент нічого не змінює і не радить переписувати | Узгоджено | — |
| 31 | DevSecOps Meets AI | Детерміновані gate-и | `--fail-on`, `policy-check`, аудит; AI не вирішує про блокування | Покрито в scope | Політики не генеруються моделлю. |
| 32 | Never Paste Secrets: Safe Prompting | Санітизація | Широкий набір форматів, невидимі символи, значення секретів ніколи не друкуються | Покрито в scope | Best effort, не DLP; ротація скомпрометованого — за людиною. |
| 33 | Reviewing AI-Generated IAM/RBAC | Over-permission | Літерали IAM `*`, K8S028–K8S030, TF001/TF002 | Частково | Effective permissions не обчислюються. |
| 34 | Dependency and Supply-Chain Risk | Pin і походження | CI001, DF004, TF006, перевірка pin; `vuln-triage` | Частково | Перевірки slopsquatting і генерації SBOM немає (SBOM runtime-залежностей створюється в CI). |
| 35 | Threat Modeling with AI | Модель загроз | `docs/threat-model.md` для самого інструмента | Поза scope | Моделі загроз для чужих систем не будуються. |
| 36 | Securing the AI Tools in Your Pipeline | AI-інструмент як привілейований актор | Дані, не інструкції; мінімальний env; агент без tools; CI002/CI004 | Покрито в scope | Kiro `tools=[]` — не ОС-пісочниця. |
| 37 | SBOMs, Vulnerabilities, and AI Triage | `vuln-triage` | Групування Grype/Trivy, дедуплікація, ранжування, підрахунок прихованого | Частково | Reachability і парсинг SBOM відсутні. |
| 38 | Secrets Management: The Hardest Part of Migration | Секрети за іменем | K8S020/K8S021, CI009, DF003, TF003 знаходять літерали | Частково | Міграції секретів немає. |
| 39 | Policy-as-Code Explained and Drafted by AI | `policy-check` | Детермінована політика з allow/deny тестами | Покрито в scope | Політики не пишуться моделлю. |
| 40 | The Security Risks of Trusting AI Output Blindly | Перевірка виходу моделі | Evidence IDs, точні цитати, відкидання невідомих полів на всіх рівнях | Покрито в scope | Перевірена цитата не доводить правильності висновку. |
| 41 | Platform Engineering: Paving the Golden Path | Golden path | — | Поза scope | Платформних шаблонів немає. |
| 42 | Internal Developer Platforms and the AI Help Desk | Help desk | — | Поза scope | Асистента з документації немає. |
| 43 | Drafting Postmortems with AI | `triage` | Часова шкала, чернетка без причини, причина — `unverified_hypothesis` | Частково | Висновки й action items — за людиною. |
| 44 | On-Call in the AI Era | Advisory-only | Жодних автодій; рекомендації без виконання | Узгоджено | — |
| 45 | Building an AI Adoption Playbook | Впровадження | CONTRIBUTING і SECURITY | Частково | Плейбук команди — поза продуктом. |
| 46 | The Verification Mindset | Верифікація як ядро | `verified: false`, evidence IDs, тести з синтетичними «галюцинаціями» | Покрито в scope | — |
| 47 | Prompt Engineering for Infrastructure Work | Промпти | Версіоновані промпти для опційних провайдерів | Частково | Бібліотеки промптів команди немає. |
| 48 | Will AI Replace DevOps Engineers? | Роль людини | — | Поза scope | Не функція продукту. |
| 49 | Learning DevOps Faster with AI | Навчання | Кожне правило пояснює чому й що робити (`rules`) | Частково | Не навчальна платформа. |
| 50 | The 1.3x Engineer | Реалістичні очікування | Офлайн-оцінка чесно показує межі (`docs/offline.md`) | Узгоджено | — |
| 51 | Kubernetes Deployment Strategies | Стратегії розгортання | K8S013–K8S017 (replicas, strategy, history) | Частково | Вибір стратегії і canary/blue-green не оцінюються. |
| 52 | Rolling Updates Explained | Rolling update | K8S001, K8S015, K8S016 | Покрито в scope | — |
| 53 | Blue-Green Deployments | Blue-green | — | Поза scope | Рантайм-стратегія. |
| 54 | Canary Releases | Canary | — | Поза scope | Рантайм-стратегія. |
| 55 | GitOps: The Declarative Deployment Model | GitOps | K8S020/K8S021: секрети не в Git | Частково | Reconcile і drift не оцінюються. |
| 56 | Health Probes: Readiness, Liveness, Startup | Probes | K8S001, K8S002 | Покрито в scope | Коректність ендпоінтів не перевіряється. |
| 57 | Zero-Downtime Deployments on Kubernetes | Zero downtime | K8S013, K8S014, K8S018, K8S019, K8S001 | Покрито в scope | — |
| 58 | Rollbacks and Release Safety | Rollback | K8S017, TF007 | Частково | Rollback не виконується. |
| 59 | Deployment vs StatefulSet vs DaemonSet | Вибір контролера | K8S011, K8S012, K8S022, K8S023 | Частково | Придатність типу контролера не оцінюється. |
| 60 | Feature Flags and Kubernetes Delivery | Feature flags | — | Поза scope | Рантайм. |
| 61 | Helm Charts Fundamentals | Чарт | HELM001, HELM002 | Частково | Рендер не виконується. |
| 62 | Helm Chart Best Practices | Практики чарта | HELM003–HELM008, K8S024 | Частково | `required`/schema-семантика не оцінюється. |
| 63 | Managing Values and Environments with Helm | Values | HELM008, HELM009, K8S031 | Частково | Precedence values не моделюється. |
| 64 | Helm vs Kustomize | Вибір інструмента | — | Поза scope | Архітектурне рішення. |
| 65 | Building Container Images: Best Practices | Образи | DF001–DF009, K8S003, K8S004, K8S009, K8S010 | Покрито в scope | — |
| 66 | Multi-Stage Docker Builds | Multi-stage | DF006 | Покрито в scope | — |
| 67 | From Source Code to a Running Pod | Збір → pod | Сигнатури збоїв по стадіях, K8S032 | Частково | Pipeline не відтворюється. |
| 68 | ConfigMaps and Secrets | Конфіг і секрети | K8S020, K8S021, K8S031 | Покрито в scope | — |
| 69 | Image Tagging, Digests, and Supply-Chain Integrity | Теги й digest | K8S003, K8S004, DF001, DF009 | Частково | Підписи й admission не перевіряються. |
| 70 | The Helm Release Lifecycle | Реліз | Сигнатури збоїв Helm у `debug` | Поза scope | Рантайм-життєвий цикл. |
| 71 | Custom Resource Definitions Explained | CRD | Сигнатура «Missing API or CRD» | Частково | CRD-схеми не аналізуються. |
| 72 | The Kubernetes Operator Pattern | Оператори | — | Поза scope | Не scope. |
| 73 | Building Your First Kubernetes Operator | Оператори | — | Поза scope | Не scope. |
| 74 | Testing Applications on Kubernetes | Тести | `k8s-review` (шар маніфестів), `flaky` | Частково | Інтеграційні/e2e шари не запускаються. |
| 75 | Integration Testing Inside Clusters | Інтеграційні тести | — | Поза scope | Не scope. |
| 76 | End-to-End Testing with Ephemeral Environments | Ephemeral env | — | Поза scope | Не scope. |
| 77 | Autoscaling in Kubernetes: HPA, VPA, Cluster Autoscaler | Автоскейлінг | K8S025–K8S027, RS001 | Покрито в scope | Cluster Autoscaler не оцінюється. |
| 78 | Resource Requests and Limits | Requests/limits | K8S005–K8S007, RS001–RS004 | Покрито в scope | QoS-евікшн не моделюється. |
| 79 | Observability for Kubernetes Applications | Спостережуваність | — | Поза scope | Рантайм. |
| 80 | Debugging Kubernetes Workloads in Production Safely | Безпечне налагодження | Сигнатури статусів у `debug`; нічого не змінює | Частково | `kubectl debug`/rollout не виконуються. |
