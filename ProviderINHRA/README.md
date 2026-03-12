# Intelegent-Store

Проект интеллектуального хранения


## `state.py`

Хранит текущее состояние в памяти:

* какой LED хотим включить
* какое текущее значение датчика
* dirty / applied
* timestamps

Это просто  **оперативная память приложения** .


## `api.py`

Это вход/выход по HTTP:

* принять команду на LED
* отдать `/state`
* отдать `/sensor/<bin_no>`
* отдать `/sensors`

API не опрашивает ПЛК.



## `worker.py`

Это главный фоновый цикл:

* берет dirty LED из `store`
* пишет их в ПЛК по Modbus TCP
* раз в секунду читает датчики из ПЛК
* обновляет `store`
* пишет события в SQLite
* пушит изменения наружу по HTTP

**реальный Modbus worker** .



## `db.py`

Пишет историю:

* `sensor_history`
* `led_history` db



## `app.py`

Собирает все вместе:

* создает `store`
* создает `db`
* создает `modbus`
* запускает **один** worker thread
* запускает Flask


## LED

<pre class="overflow-visible! px-0!" data-start="1392" data-end="1595"><div class="relative w-full mt-4 mb-1"><div class=""><div class="relative"><div class="h-full min-h-0 min-w-0"><div class="h-full min-h-0 min-w-0"><div class="border border-token-border-light border-radius-3xl corner-superellipse/1.1 rounded-3xl"><div class="h-full w-full border-radius-3xl bg-token-bg-elevated-secondary corner-superellipse/1.1 overflow-clip rounded-3xl lxnfua_clipPathFallback"><div class="pointer-events-none absolute inset-x-4 top-12 bottom-4"><div class="pointer-events-none sticky z-40 shrink-0 z-1!"><div class="sticky bg-token-border-light"></div></div></div><div class=""><div class="relative z-0 flex max-w-full"><div id="code-block-viewer" dir="ltr" class="q9tKkq_viewer cm-editor z-10 light:cm-light dark:cm-light flex h-full w-full flex-col items-stretch ͼ5 ͼj"><div class="cm-scroller"><div class="cm-content q9tKkq_readonly"><span>клиент -> POST /led/5</span><br/><span>      -> api.py</span><br/><span>      -> store.set_led(...)</span><br/><span>      -> dirty=True</span><br/><span>      -> worker увидел dirty</span><br/><span>      -> write_modbus_led(...)</span><br/><span>      -> mark_led_applied()</span><br/><span>      -> лог в БД</span></div></div></div></div></div></div></div></div></div></div></div></div></pre>



## Датчики

<pre class="overflow-visible! px-0!" data-start="1614" data-end="1770"><div class="relative w-full mt-4 mb-1"><div class=""><div class="relative"><div class="h-full min-h-0 min-w-0"><div class="h-full min-h-0 min-w-0"><div class="border border-token-border-light border-radius-3xl corner-superellipse/1.1 rounded-3xl"><div class="h-full w-full border-radius-3xl bg-token-bg-elevated-secondary corner-superellipse/1.1 overflow-clip rounded-3xl lxnfua_clipPathFallback"><div class="pointer-events-none absolute inset-x-4 top-12 bottom-4"><div class="pointer-events-none sticky z-40 shrink-0 z-1!"><div class="sticky bg-token-border-light"></div></div></div><div class=""><div class="relative z-0 flex max-w-full"><div id="code-block-viewer" dir="ltr" class="q9tKkq_viewer cm-editor z-10 light:cm-light dark:cm-light flex h-full w-full flex-col items-stretch ͼ5 ͼj"><div class="cm-scroller"><div class="cm-content q9tKkq_readonly"><span>worker</span><br/><span>  -> read_sensor_modbus(bin_no)</span><br/><span>  -> store.update_sensor(...)</span><br/><span>  -> если changed:</span><br/><span>       db.log_sensor(...)</span><br/><span>       push_sensor_change(...)</span></div></div></div></div></div></div></div></div></div></div></div></div></pre>
