# Практичні контракти RADEA після аудиту статей №21–80

Цей документ описує реалізацію, а не обіцяє повне покриття всіх тем серії.
Оператори, blue-green/canary, міграційні оркестратори й IDP поза scope; Kubernetes, Helm, Dockerfile, CI і Terraform покриті детермінованими перевірками (див. `feature-matrix.uk.md`).

| Прогалина аудиту | Реалізований контроль | Автоматична перевірка |
| --- | --- | --- |
| F1 — секрети/PII | JSON та короткі assignments, різні URL schemes, signed URLs, PEM, internal hosts/emails/private IPv4; вихід очищається повторно; raw bypass заборонено | Негативні/позитивні fixtures та redacted PR flow |
| F2 — ризики залежать від LLM | Повний bounded plan parse, локальні delete/replace, локальні literal IAM rules, policy-check з allow/deny | Delete/replace за порожньої відповіді й при збої LLM; allow/deny fixtures |
| F3 — неперевірені твердження | Контракт per command, evidence IDs, точні цитати, discard unknown fields, керовані помилки | Вигадані посилання, неправильні quotes/enums/types і spoofed metadata |
| F4 — втрата контексту | Потокове bounded читання; head/tail; omission metadata; план має незалежний бюджет | Tail failure, довгий Terraform, oversized files/lines, PEM у хвості |
| F5 — немає аудиту/provenance | JSON draft/verified/provenance, private metadata-only audit, явні unverified causes/human fields; числові baseline deltas | Audit privacy/permissions/failures; matched metrics/zero baseline |
| F6 — неперевірені інтеграції | GitHub text-job adapter та bounded plan artifact review без виконання PR коду; інші vendor adapters experimental | API data → model boundary → validated comment; fork/redirect/artifact negatives |
| F7 — supply chain | uv lock, hashed exports, action SHA pins, SBOM, checksum, promotion of tested artifact, provenance | Locked installs, tests across Python, wheel smoke та workflow contracts |
| F8 — межі довіри | Невідомий provider відхиляється; remote Ollama opt-in/HTTPS, loopback local; мінімальний Kiro env; threat model | Routing negatives, credential exclusion у реальному дочірньому fake executable |

Власник main залишається єдиним writer. Required CI/PR gate — окреме GitHub правило;
його застосовано без bypass: PR і всі п’ять CI checks обов’язкові. Це налаштування
GitHub, а не наслідок наявності workflow-файлів; перевіряйте його при перенесенні репозиторію.

Чесні межі: redaction — best effort, не універсальний DLP. Перевірена цитата не доводить
правильність висновку. Literal IAM rule не замінює аналіз effective permissions.
Kiro tools=[] і cwd не є OS sandbox. Реальна якість backend-ів та економія часу
потребують live smoke й human-scored pilot; початковий corpus синтетичний.
Див. `evaluation.md`, `threat-model.md` та регресійні тести.
