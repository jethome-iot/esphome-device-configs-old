# Что взять из `esphome-device-configs` и как разложить YAML

Сравнение нового репозитория `esphome-device-configs` с этим (`feature/add-pm380`, рабочее дерево
на 2026-10-07). Это план, а не сделанная работа.

## Решения

Номера — из таблицы в разделе 1.

| # | Что | Решение (2026-10-07) |
|---|---|---|
| 1 | `web_server_idf` (фикс паники при зависшем клиенте `/events`) | Пока не делаем. Вернуться до первого релиза или при bump ESPHome, где фикс уже есть |
| 2 | Board и features packages вместо CPU-блоков в PM-конфигах | Сделано: `include/boards/`, `include/features/` (без `jethome_board_info` и `status_indicator`) |
| 3 | `fram_store` из `feature/fram-store` | Сделано: `fram_store` и `i2c_eeprom` с `type: fram`, карта FRAM layout v1 (`include/features/fram.yaml`), записи счётчиков в `components/pm_energy` |
| 4 | Один общий форк меню | Пока не делаем. Наши хунки: `type: value`, `reset_menu()`, `apply_on_confirm`, `weight` |
| 6 | CI и pre-commit | Пока не делаем |
| 8 | Пароль на web-интерфейс | Пока без пароля |
| — | Где развивать PM: мигрировать этот репо или перенести PM-пакеты в новый | Не решено |

## Коротко

- **Версия ESPHome одна** — 2026.9.1 в обоих репо. Расходятся копии компонентов. Наш форк
  `display_menu_base` снят со старого upstream, поэтому каждый PM-конфиг даёт 9 warning
  `register_action(...) is missing the synchronous= parameter`.
- **Самое полезное для PM лежит в невлитых ветках нового репо**, а не в `dev`:
  - `feature/fram-store` — `fram_store`, `i2c_eeprom type: fram`, `features/fram.yaml` с картой FRAM;
  - `refactor/shared-packages` — общие display, menu и buttons, контракт board page, `display_model`;
  - `feature/menu-deferred-edit` — аналог нашего `apply_on_confirm`;
  - `feature/meter-cal-record` — запись калибровки (см. `doc/pm220-calibration.md`).
- **Целевая раскладка уже есть в истории этого репо.** `origin/dev` здешнего клона — история нового
  репо до #220 в раскладке `devices/JXD/packages/...`. `master` — промежуточный вариант
  (`packages/` в корне, `dist/`, CI, только R6). `feature/add-pm380` ответвлена от `1278d39`
  (декабрь 2025) и ни про одну из этих раскладок не знает.
- **`esphome config` проходят 3 конфига из 5**: все PM. Оба R6 падают (ниже).

## Что есть в репо кроме PM

| Конфиг | `esphome config` |
|---|---|
| `JXD/jxd-pm220-e1eth.yaml` | OK (warnings: synchronous=, strapping) |
| `JXD/jxd-pm380-e1eth.yaml` | OK |
| `JXD/jxd-pm380-e1eth_v2.yaml` — тот же PM380 плюс `tests/full-test.yaml`, без FN, name `-test` | OK |
| `JXD/jxd-r6-e1eth-lcd-eth.yaml` | FAIL: нет `../include/jxd-r6-eth.yaml` (переименован в `ethernet.yaml` в 07d483f), затем не задан `${timezone}` — у `pcf8563-time.yaml` нет default |
| `JXD/jxd-r6-e1eth-lcd-wifi.yaml` | FAIL: нет `JXD/secrets.yaml` для `!secret` и тот же `${timezone}` |
| E1 (`E1/jethub-e1-pd76-r5-*`) | только в ветке `feature/add-e1`, здесь пустая `E1/`. Использует `include/ethernet.yaml` и `wifi.yaml` — при миграции их не трогать |
| `tests/*.yaml` | аппаратные self-test packages; общие common, i2c, webui подключены в `_v2` |
| `components/{groups,modbus,modbus_controller,modbus_server_group}` | нужны только R6 |

## 1. Что ещё можно забрать

По убыванию пользы.

| # | Что (пути в новом репо) | Что даёт PM | Усилие и риски | Брать? |
|---|---|---|---|---|
| 1 | `components/web_server_idf` + `features/web-server-idf-backport.yaml`; в ветке `fix/httpd-stack` стек httpd 8192 | Фикс use-after-free при зависшем клиенте `/events` (ESPHome PR #17800, в 2026.9.1 его нет). У PM `web_server v3` с `/events` — тот же риск паники через часы работы | S. Удалить после bump на релиз с #17800 | Да, первым |
| 2 | `boards/jxd-cpu-e1eth.yaml` (версия из `refactor/shared-packages`) + `features/{i2c,rtc-time,vin-measure,display-off}.yaml` | Убирает ~150 строк CPU-блоков из `jxd-pm220-e1eth-base.yaml` и обоих PM380. PM380 получает HA time и timezone по умолчанию вместо зашитой `Europe/Moscow` | S–M, риски ниже | Да |
| 3 | `feature/fram-store`: `components/fram_store`, `i2c_eeprom type: fram`, `features/fram.yaml` | Две копии на slot, переживает обрыв питания, host-тесты. Заменяет наши `EnergyStore` / `ChannelEnergyStore` и убирает `esphome: includes: *.h` | M. Ветка не влита | Сделано |
| 4 | Форк меню (`components/display_menu_base`, `graphical_display_menu`) + `scripts/vendored-diff.py`, маркеры `JetHome:`, тесты | Свежий upstream (уходят 9 warnings), `back()` возвращает bool, пустые submenu, weight на корне, pre-commit следит за устареванием | M. Перенести наши хунки (`type: value`, `reset_menu()`, `apply_on_confirm`) или взять `deferred_edit` из `feature/menu-deferred-edit` — но там BACK применяет значение, а у нас отменяет. Лучше один общий форк | Да |
| 5 | Общие display packages из `refactor/shared-packages` | Удаляет `jxd-pm{220,380}-e1eth-buttons.yaml` и большую часть двух display-файлов | M, зависит от п.4 | Да |
| 6 | CI и гигиена: `.pre-commit-config.yaml`, `.github/workflows/ci.yml`, `firmwares.yaml` + `scripts/firmware-matrix.py`, `esphome-release-check.yml`, dependabot, `requirements-dev.txt`, `scripts/setup.sh` | Валидация всех конфигов на каждый push — битые R6 выше не прошли бы незамеченными | S для lint/validate, M для compile-матрицы (self-hosted runners) | Да |
| 7 | `components/status_indicator` + `features/factory-reset.yaml` | Паттерны LED вместо `red_led`; FN 10 с → factory reset | S, риски ниже | Да |
| 8 | Веб-безопасность: `web_server: auth:` (S) или `web_auth` + `web_origin_guard` (M), ветка `feature/ota-password` | Сейчас из LAN без пароля доступны «Reset All Energy Counters», Run/Clear calibration, Ref voltage/current | S–M | Да, минимум `auth:` |
| 9 | `scripts/build-dist.py`, `dist/`, `doc/DIST.md` | Импорт в ESPHome Builder | M, проблемы ниже. После п.3 | Позже |
| 10 | `features/firmware-update.yaml`, firmware page/menu, `firmware_rollback`, release workflows | Обновления с fw.jethome.com | L, нужны slug'и и секреты | Когда PM пойдёт в релиз |
| 11 | Конвенции docs: `CLAUDE.md`, `doc/ARCHITECTURE.md`, `doc/DEVELOPMENT.md` | Межфайловые контракты PM станут явными | S | Вместе с миграцией |
| 12 | QEMU (`scripts/qemu.sh`, `packages/qemu/*`, `virtual_display`) | Меню, страницы и rollover счётчиков без железа | L | Позже |
| 13 | `features/storage.yaml` + `crash_report` | Запись паники на flash | L: новая partition table, только USB-прошивка | По желанию |
| 14 | `feature/debug-menu` | Heap и PSRAM в Settings | S | По желанию |

**Риски:**
- **п.2.** Переименования меняют entity_id в HA (`PCB TEMPERATURE` → `PCB Temp`, VIN/PoE →
  `Input voltage`, `cpu_board_temp` → `pcb_temp`, `vin_voltage` → `vin_meas`) — делать до первого
  релиза. На CPU Rev 2.0 нет FN — overlay с `- id: !remove fn_button`. В новом `i2c.yaml` нет
  `timeout: 100ms`. В новом `features/network.yaml` стоит `power_pin: GPIO15` — это CS ATM90E32
  на PM380, нужен `power_pin: !remove`.
- **п.7.** `factory-reset.yaml` вызывает `user_storage->request_format()` — без LittleFS его надо
  править. `energy_clear` через `!extend` на `run_factory_reset` встанет после
  `App.safe_reboot()` и не выполнится — нужен hook до reboot.
- **п.9.** Flatten как в `build-dist.py` на `jxd-pm380-e1eth.yaml` даёт три одинаковых
  `energy_counter_${slot}`: vars из `!include` теряются (в новом репо vars нигде нет). Нужно
  научить build-dist применять vars. (`esphome: includes: *.h`, который скрипт отверг бы как
  локальный путь, уже убран: описания записей FRAM в компоненте `pm_energy`.)

**Межфайловые контракты PM:** `fram_cpu`, `pcf8563_time`, `energy_loaded`, globals `energy_*`,
`display1`, `check_blank_page`, `display_off_s`, `ip`, `link_icon`, `info_submenu`,
`menu_settings_id`, slot'ы `fram_counter_00–09` с записями из `pm_energy` и порядок сохранения:
каналы PM220 раньше сумм.

### Что обновилось в уже перенесённом

- **Иконки статуса.** В новом репо `link_icon` переехал в `display/network-icons.yaml`, так что
  `network.yaml` работает и без дисплея. HA-иконка там проверяет `is_connected()`; наш
  `is_connected_with_state_subscription()` точнее, его стоит отдать в новый репо.
- **Sorting groups.** В `refactor/shared-packages` группу объявляет package, которому принадлежат
  сущности. Наши `device` и `mains` стоит привести к `group_*`.
- **Калибровка.** `jethome_board_info` в `meter-cal-record` стал списком (несколько EEPROM) — для
  PM нужна эта форма: 0x54 и 0x56. Vendored `i2c_eeprom` уже взят из `fram-store` (`type: fram`),
  pilotak больше не используется. `jethome_board_info` пока не перенесён: он включает
  write-protect на `eeprom_cpu`, а self-test в `tests/test-i2c.yaml` в неё пишет.
- **Карта FRAM.** Принят layout v1 нового репо (`include/features/fram.yaml`): 0x0000–0x01FF —
  стенд, `fram_store_meter` 0x0200–0x06BF, счётчики 0x06C0–0x0DDF, свободно с 0x0DE0.
  Пользовательская калибровка PM220 пойдёт новым store в свободную область
  (`doc/pm220-calibration.md`, §3.2).

## 2. Раскладка YAML

### Как в новом репо

- **Device config** (`devices/<family>/<device>.yaml`) — только `substitutions`, `packages:`,
  `esphome:` и `dashboard_import`.
- **Path substitutions** относительно файла: `assets: ../../assets`, `components: ../../components`,
  `boards: packages/boards`, `features: packages/features`, `display: packages/display`. Пакеты
  пишут `!include ${features}/x.yaml`; каждый package сам объявляет свои external components.
- **`packages/` по ролям:** `boards/` — файл на PCB; `features/` — шины и функции; `display/` —
  страницы через `id: !extend display1`, menu с точками расширения `info_submenu` /
  `menu_settings_id` и `weight`, buttons; `qemu/` — overlays.
- **Имена:** ключи packages в snake_case по роли, файлы в kebab-case без префикса устройства.
  Vars нет, id фиксированные, контракты описаны в `ARCHITECTURE.md`.
- **Дефолты substitution** задают сами пакеты (`timezone: UTC`, `display_model`).
- **Логика** в компонентах с host-тестами, YAML тонкий.
- **`dist/<device>.yaml`** генерирует `build-dist.py`; URL импорта всегда
  `dist/<device>.yaml@master`; `firmwares.yaml` перечисляет все device configs.

### Как здесь

Плоские `JXD/*.yaml` и `include/jxd-<device>-*.yaml`, относительные `../include`, `../fonts`. В
device config много железа (PM380 — 241 строка с esp32, i2c, eeprom, adc, time, web_server).
External components в device config, `.h` через `esphome: includes`, везде vars. Self-test
подключён в боевой конфиг (`_v2`).

### Целевая раскладка

```
devices/JXD/
  jxd-pm220-e1eth.yaml
  jxd-pm380-e1eth.yaml
  jxd-pm380-e1eth.factory-test.yaml   # вместо _v2, без dashboard_import
  packages/
    boards/   jxd-cpu-e1eth.yaml, jxd-cpu-e1eth-rev2.yaml (!remove fn_button),
              jxd-d3-pm1-6.yaml, jxd-d3-pm1-6-channel.yaml (vars {channel}),
              jxd-d3-pm3-3.yaml, jxd-d3-pm3-3-phase.yaml (vars {phase, n})
    features/ i2c, rtc-time, network, vin-measure, display-off, factory-reset, fram,
              web-server-idf-backport, energy.yaml, energy-slot.yaml,
              energy-bl0906.yaml (+ energy-bl0906-channel.yaml), energy-atm90e32.yaml
    display/  display.yaml, buttons.yaml, menu.yaml, blank-page, time-page, network-icons,
              menu-items-network, menu-serial, energy-page.yaml, menu-energy.yaml,
              menu-energy-slot.yaml, menu-energy-row.yaml,
              pm220-status-page.yaml, pm220-channels-page.yaml, pm220-menu-channels.yaml,
              pm380-status-page.yaml, pm380-menu-phases.yaml, pm380-menu-calibration.yaml
    factory-test/  common.yaml, i2c.yaml, webui.yaml
assets/fonts/, assets/res/   (бывшие fonts/ и images/icons/)
components/  scripts/  dist/  doc/  firmwares.yaml
```

Общие файлы без префикса, специфичные для счётчика — с `pm220-` / `pm380-`. Платы — по имени PCB.

### Дубли и как их слить

| Сейчас | Строк | Отличия | Во что |
|---|---|---|---|
| `jxd-pm220-energy-slot.yaml` / pm380 | 55/55 | строка комментария | `features/energy-slot.yaml` |
| `jxd-pm220-energy-slot-menu.yaml` / pm380 | 24/24 | нет | `display/menu-energy-slot.yaml` |
| `jxd-pm220-energy-menu-item.yaml` / pm380 | 7/7 | нет | `display/menu-energy-row.yaml` |
| `jxd-pm220-energy-page.yaml` / pm380 | 37/37 | комментарий | `display/energy-page.yaml` |
| `jxd-pm220-e1eth-buttons.yaml` / pm380 | 103/97 | DOWN → `channels_page`; оба тянут `jxd-r6-e1eth-buttons.yaml` (217 строк) ради PCA9554 | общий `display/buttons.yaml` с контрактом board page |
| `jxd-pm220-energy.yaml` / pm380 | 310/256 | только источник дельты и список счётчиков в «Reset all» | `features/energy.yaml` + `energy-bl0906.yaml` / `energy-atm90e32.yaml` |
| `jxd-pm220-e1eth-display.yaml` / pm380 | 195/258 | P total, id температуры и VIN, корень меню, Calibration | общие `display.yaml`, `menu.yaml`, `menu-energy.yaml` + `!extend` от устройства |
| `jxd-pm220-status-page.yaml` / pm380 | 58/62 | содержание | оставить раздельными |
| `JXD/jxd-pm380-e1eth.yaml` / `_v2` | 241/243 | name, full-test, FN | один config + overlay factory-test + overlay CPU Rev 2.0 |
| CPU-блоки в PM220 base и обоих PM380 | ~150 ×2 | фильтр и id VIN, time inline | `boards/jxd-cpu-e1eth.yaml` + features |
| 6 блоков `channel_N` BL0906 и 3 блока `phase_x` ATM90E32 | — | номер | package с vars и `- id: !extend bl0906_chip` (проверить `esphome config` первым делом) |
| `vars: {display_settings_id: display1}` в 8 местах | — | всегда `display1` | убрать var |

- **Energy.** Общее (globals, Today/Yesterday/Month/Last month, rollover, 3 slot'а, «Reset all»)
  уходит в `features/energy.yaml`. Контракт: `script energy_add(delta_wh)` и hook'и
  `energy_reset_hook` / `energy_refresh`, которые устройство дополняет через `!extend`. Записи
  FRAM уже общие: `CounterRecord` и `PeriodsRecord` в `components/pm_energy`.
- **Display.** В общее уходит всё, кроме P total (PM220 — `total_power` чипа, PM380 — сумма фаз;
  PM380 стоит завести template sensor `total_power`), id температуры и VIN (унифицировать:
  `meter_temperature`, `vin_meas`), корня меню и Calibration у PM380.

### План миграции

После каждого шага все конфиги проходят `esphome config`.

0. **Baseline (S).** Починить R6 (путь `ethernet.yaml`, `timezone: UTC` по умолчанию в
   `pcf8563-time.yaml`). Завести `firmwares.yaml`, `firmware-matrix.py` и CI Validate. Взять
   pre-commit из нового репо, выкинуть сломанные pylint и flake8. Решить судьбу R6 и E1 в этой
   ветке: актуальный R6 живёт в `master` / `origin/dev`, здешний — замороженная копия.
1. **Перенос (S, отдельный commit, `git mv` без правок).** `fonts/` → `assets/fonts/`,
   `images/icons/` → `assets/res/`; PM-конфиги в `devices/JXD/`, PM-include'ы в `packages/*`. R6 и
   E1 остаются в `JXD/` и `include/`; общие для них файлы копировать, а не переносить, до ухода
   R6/E1. В `.gitignore` добавить `devices/*/.esphome/`.
2. **Board и features (S–M).** Переименования сущностей — сейчас, до релиза.
3. **Слияние дублей (M).** Затем удалить `_v2` и все `jxd-pm{220,380}-*` из `include/`.
4. **Компоненты (M):** форк меню, `status_indicator`, `web_server_idf`. `i2c_eeprom` (fram) —
   сделано.
5. **Self-tests (S)** в `packages/factory-test/`; убрать запись в байт 0x0001 EEPROM 0x54/0x56
   (см. §3.4 `doc/pm220-calibration.md`).
6. ~~**FRAM (M):** `fram_store` после утверждения карты; `.h` исчезают.~~ Сделано.
7. **`dist/` (M):** `build-dist.py` с фиксом vars, после этого `dashboard_import`.
8. **Релизы (L):** firmware-update, release workflows, slug'и.

Если раскладка совпадёт по путям с новым репо, PM-пакеты потом можно перенести туда простым
копированием.

### `dashboard_import`

- Текущие `package_import_url` (`github://jethome-iot/esphome-configs/JXD/...@master`)
  неработоспособны: raw.githubusercontent отдаёт по ним 404. Это может быть и потому, что
  репозиторий закрытый, но ESPHome Builder ходит без авторизации, так что для импорта
  результат тот же.
- Правило из `DIST.md`: URL указывает на сгенерированный `dist/<device>.yaml@master`, а не на
  исходник; тогда раскладку исходников можно менять свободно. Имена файлов в `dist/` не
  переименовывать.
- Репо в URL выбрать окончательно сразу: GitHub-редирект не спасёт, если старое имя занято другим
  репо (так случилось с `esphome-device-configs`).
- Builder переименовывает устройство через `${name}` — у PM380 `lowercase_name` заменить на `name`.
- У overlay-конфигов (`*.factory-test.yaml`, `*.qemu.yaml`) `dashboard_import` нет.

## Попутные находки

- **PM380:** `time:` inline с `Europe/Moscow`, нет HA time и `setup_time`, substitution
  `timezone: GMT` не используется; `logger: VERBOSE`, `atm90e32: VERBOSE`.
- **Pre-commit:** pylint вызывает несуществующий `script/run-in-env.py`; flake8 настроен на
  `^(esphome|tests)/.+\.py$` и не покрывает `scripts/`; `no-commit-to-branch` на dev/release/beta
  скопирован у ESPHome.
- **Устаревшее в доках:** README badge 2025.10.5; `setup.sh` требует Python ≥3.11, а ESPHome
  2026.9.1 нужен ≥3.12.
- **`atm90e32.zip` в git** — снимок старого upstream atm90e32, конфиги его не используют.
- **Мусор:** пустые каталоги `cpp/` и `E1/`.
