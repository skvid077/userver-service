# Проверка на Ubuntu в VirtualBox

В чистом клоне репозитория выполнена команда `bash run.sh` с обычными параметрами: 10 пар с трассировкой, 6 пар без неё, 8 прогревов. Все 40 сборок успешны. Unit-тест прошёл с GNU ld и LLD; схемы конфигурации и динамические зависимости совпали.

| Параметр | Значение |
| --- | --- |
| Ubuntu | 22.04.5 LTS |
| Ядро | 5.15.0-198-generic |
| VirtualBox | 7.2.22, Windows с Hyper-V |
| Docker Engine | 29.9.2 |
| Виртуальная машина | 4 CPU, 12 ГиБ памяти |
| Контейнер | 4 CPU (0–3), 8 ГиБ, без swap |
| Образ и инструменты | Те же digest и версии, что в основной серии |

В этой серии полная сборка с LLD быстрее во всех 16 измеряемых парах. Все отдельные запуски, включая прогревы, находятся в [all-results.csv](all-results.csv). Сырой вывод Clang Build Analyzer — в `profile-*/analyzer.txt`.

Для этой VM пришлось заменить нестабильные виртуальные часы на TSC. Параметры гостевого ядра сохранены в [verification/kernel-command-line.txt](verification/kernel-command-line.txt). Они относятся к этому компьютеру.

Предварительные запуски были остановлены из-за ошибок часов VM и приостановки компьютера; их данные сохранены локально. Здесь опубликован один полный последовательный прогон после устранения этих проблем.

Во время подготовки и измерений часы Ubuntu сверялись с таймером Windows раз в секунду, без дополнительной CPU-нагрузки. За 2818 с максимальное расхождение составило 0,079 с. Сохранены [все отсчёты](verification/jammy-build-after-resume-clock-probe.jsonl) и [результат проверки](verification/jammy-build-after-resume-clock-probe-summary.json). До запуска часы дополнительно проверены под нагрузкой на все 4 CPU.

Внешние отсчёты охватывают все 40 сборок. Максимальный размах расхождения в пределах одной сборки — 2,3 мс; расчёт сохранён в [verification/clock-coverage.json](verification/clock-coverage.json).

Проверка сохранённых данных из корня репозитория:

```bash
python results/ubuntu/verification/verify_new_run.py . results/ubuntu results/ubuntu/verification/container-inspect.json
```

Проверка использует исходный `scripts/verify_results.py`; изменён только выбор каталога данных и чтение сведений о Linux-хосте из Docker inspect. Исходники проверяющего скрипта сохранены. Результат — [verification/fresh-data-verification.txt](verification/fresh-data-verification.txt).

Эта проверка относится к отдельной серии Ubuntu/VirtualBox. Основной отчёт и корневой CSV описывают серию Windows/WSL 2.
