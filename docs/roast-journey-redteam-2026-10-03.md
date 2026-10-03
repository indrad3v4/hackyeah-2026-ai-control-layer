# Чырвоная каманда: adversary walk шляху карыстальніка WARRNT

Дата: 2026-10-03 · Аб'ект: `/root/.hermes/hackyeah/warrnt` (master 9dbb944), люстра `ai-control-layer/node/warrnt/**` (IDENTICAL, праверана `diff -q`)
Абяцанне, якое правяраем: **«ніводнае дзеянне не выйшла па-за мяжу без вердыкту і запісу»**.

Метад: чытанне кода + жывыя прагоны праз `TestClient` на рэальным `create_app`. Кожная знаходка ніжэй альбо пацверджана прагонам (пазначана «ПАЦВЕРДЖАНА»), альбо мае дакладную спасылку `file:line`. Без спасылкі — не ўвайшло.

Канфігурацыя: 1 канонічны вузел + люстра-копія вузла ў сабмішэне. Люстра не адрозніваецца — усе дэфекты адносяцца да абодвух.

---

## 0. Мадэль пагрозы

| Актор | Што хоча | Што мае |
|---|---|---|
| агент | выканаць забароненае | свой (agent, token, warrant); сеткавы доступ да `/mcp` |
| аператар | схаваць сляды | доступ да консольных эндпоінтаў `POST /reset`, `/revoke`, `/api/breakglass` |
| уладальнік хоста | падмяніць усё | рэпа, `state/receipts.jsonl`, `state/issuer.key`, `state/anchors.jsonl` |
| суседні працэс | гонка паміж рашэннем і дзеяннем | агульныя in-memory аб'екты `grants`, `agents`, `warrants` (аднавосевы uvicorn, шматпатокавы) |
| памылка кантролера | — | `upstream.call` па-за `try`, `gate_registry.run` кідае |

---

## 1. Спіс вектараў

### V1 · Control plane без аўтэнтыфікацыі — **OPEN** (ПАЦВЕРДЖАНА, востры)

**Сцэнар:**
1. Любы, хто дасягае порт 8099 (`config.py:38`, bind `0.0.0.0` па змаўчанні `config.py:38` + `api.py`), шле `POST /api/breakglass {"human":"attacker","agent":"report-bot","tool":"crm.bulk_export","reason":"x"}`.
2. Вузел вяртае `{"id":"BG-0001","human":"attacker",...,"expires_in_s":900}` — подпіс сапраўдны, бо яго ставіць сам вузел.
3. Агент `report-bot` цяпер можа выканаць `crm.bulk_export` (policy pause падняты, гэйт `order_policy.py:26-33`).

**Чакаемы эфект:** подпіс і запіс ёсць, бо вузел давярае загалоўку/целу без праверкі асобы — «вердыкт і запіс» ёсць, але чалавекам там не пахне.

**Доказ:** `api.py:103-114` (`create_app` без `Depends`/auth), `api.py:240-255` (`/revoke` не аўтэнтыфікаваны), `api.py:258-284` (`/api/breakglass`), `api.py:307-310` (`/reset`), `api.py:313-338` (`/_dev/tamper`). ПАЦВЕРДЖАНА: `POST /revoke` → `200`; `POST /api/breakglass` → grant `BG-0001` выдадзены з `human="attacker"`.

**Тэст, які гэта даказвае:** `test_control_plane_requires_auth` — усе мутацыйныя эндпоінты без крэдэнталаў павінны вяртаць 401/403.

---

### V2 · `/reset` знішчае ланцуг, а `verify` і `anchor` «зелянеюць» — **OPEN** (ПАЦВЕРДЖАНА, найвастрэйшы)

**Сцэнар (самы кароткі спосаб знішчыць сведчанні, пры гэтым застацца «чыстым»):**
1. Аператар робіць забароненае (напр. шэраг `deny`/`revoke` запісаў).
2. `POST /reset` → `proxy.issue_all(reset_registry=True)` → `registry.reset()` (**`registry.py:72-77`**: `self.entries = []; open(self.path,"w").close()`).
3. `GET /verify` → `{"ok": true, "length": 0}`; `GET /anchor` → `{"ok": true, "signed": true, "head": "0000...", "length": 0}`.

**Чакаемы эфект:** файл `receipts.jsonl` фізічна пусты; ланцуг «вярэ ды зялёны»; anchor падпісаў GENESIS (`api.py:95-96` `_seal_reset` → `anchor.seal(GENESIS, 0)`), таму чысціня выглядае як подпісам зацверджаная. Атака наогул не дае чырвонага вердыкту — яна дае два зялёных.

**Доказ (ПАЦВЕРДЖАНА):** да `/reset` — `verify ok=True length=2`; пасля — `verify ok=True length=0`, `anchor verdict={'ok': True, 'signed': True, 'head':'0000...0000', 'length':0}`. Код: `api.py:307-310`, `api.py:95-99`, `registry.py:72-77`, `registry.py:62-70` (`verify()` пустога спісу = `ok True`), `anchor.py:66-67` (голас без запісаў = `ok True`).

**Дадаткова (fail-open anchor):** нават калі б `_seal_reset` не зваўся, выдаленне `anchors.jsonl` дае `anchor.verify → {"anchored": false, "ok": true}` (`anchor.py:66-67`) — адсутнасць сведчання трактуецца як «усё добра».

**Тэст, які гэта даказвае:** `test_reset_cannot_erase_history_or_must_set_evidence_destroyed`.

---

### V3 · PII-значэнні трапляюць у append-only ланцуг — **OPEN** (ПАЦВЕРДЖАНА, востры)

**Сцэнар:**
1. Агент шле `crm.read {"table":"tickets","fields":["email","pesel"],"pesel_value":"44051401359","email_value":"jan@x.pl"}`.
2. Рашэнне — `redact`, палічаныя палі прыбіраюцца з payload да upstream (`policy.strip_pii`, `proxy.py:146-148`).
3. Але **агаловак запісу** пішацца з *арыгінальнага* `params` (`proxy.py:128` → `_receipt(..., params, ...)`), а не з `exec_params`. `_receipt` серыялізуе `params` у json (`proxy.py:217-224`).

**Чакаемы эфект:** чыстае палітычнае абяцанне («PII не трапляе да upstream») тэхнічна выканана, але сама сістэма кантролю стала сховішчам PII: значэнні PESEL/email ляжаць у `receipts.jsonl`, у hash-ланцугу і аддаюцца бяз-аўтэнтыфікаваным `GET /receipts` (V1).

**Доказ (ПАЦВЕРДЖАНА):** рашэнне `redact`; у `/receipts` знойдзен 1 радок са зместам params:
`{"email_value": "jan@x.pl", "fields": ["email","pesel"], "pesel_value": "44051401359", "table": "tickets"}`.
Код: `proxy.py:128` (запіс арыгінальных params), `proxy.py:217-224` (params → json у ланцуг), `policy.py:34-61` (strip_pii ўплывае толькі на `exec_params`).

**Тэст, які гэта даказвае:** `test_receipt_never_stores_pii_values` — пасля `redact`-выкліку з вядомымі значэннямі PII тыя значэнні не павінны сустракацца ні ў адным радку ланцуга.

---

### V4 · Рэплэй статычнага токена — **OPEN**

**Сцэнар:**
1. Злоўлены (перахоплены, з лога прамежкавага проксі) загаловак `X-WARRNT-Agent` + `X-WARRNT-Token` жыве, пакуль жыве warrant.
2. Токен вылічваецца дэтэрмінавана з ключа і id (без nonce, без тэрміну): `warrants.py:48-51` — `hmac(key, f"tok:{agent}:{warrant_id}")[:24]`.
3. Аўтэнтыфікацыя — проста параўнанне загалоўкаў (`api.py:208-209`). Няма request-подпісу, няма timestamp, няма аднаразовасці.

**Чакаемы эфект:** любы, хто бачыў адзін сапраўдны выклік, можа яго паўтараць, пакуль warranted не адкліканы/не скончыўся TTL. «Дзеянне прайшло пад вердыктам» — так; «пад вердыктам гэтага выкліку» — не.

**Доказ:** `warrants.py:48-51`, `api.py:208-209`, `proxy.py:79-84` (праверка ідэнтычнасці па `agent.token`).

**Тэст, які гэта даказвае:** `test_replayed_token_is_refused` — другі выклік з тым жа (agent, token) без свежага nonce павінен быць адхілены.

---

### V5 · Гонка single-use у break-glass — **OPEN**

**Сцэнар:**
1. Два суседнія выклікі (тэрэдpool uvicorn) адначасова заходзяць у `intercept` з адным і тым жа грабам.
2. Абодва выклікаюць `gate_registry.run` → гэйт `break_glass.py:14-21` → `breakglass.active()` (чытае `grant.state`, **не змяняе яго**, `breakglass.py:95-117`).
3. Абодва бачаць `state == "active"`, абодва атрымліваюць `allow`.
4. `consume()` выклікаецца **пасля** гэйтаў (`proxy.py:122-124`) — не атамна з `active()`.

**Чакаемы эфект:** абяцанне «single_use: True» (`api.py:283`) парушаецца: адзін grant = два выкананыя дзеянні; у ланцугу два `allow` з адным `break_glass` id, другі `consume` вяртае `None` і гэта нікога не спыняе.

**Доказ:** `breakglass.py:95-117` (`active` без мутацыі стану/без `_lock`), `breakglass.py:122-130` (`consume`), `proxy.py:121-124` (разрыў паміж `run` і `consume`). У `BreakGlassRegistry` няма `threading.Lock` (супастаў: `registry.py:25` мае `RLock`) — **UNKNOWN** толькі на ступені «ці рэальна адначасова», але дэфіцыт атамнасці — факт (OPEN).

**Тэст, які гэта даказвае:** `test_breakglass_single_use_under_concurrency` — N адначасовых выклікаў з адным грабам даюць роўна 1 `executed`.

---

### V6 · Выкананне не запісваецца, калі upstream падае пасля дзеяння — **OPEN** (востры)

**Сцэнар:**
1. Рашэнне `allow`, запіс-рашэнне ўжо ў ланцугу (`proxy.py:128`).
2. `result = self.upstream.call(...)` — выконвае дзеянне (`proxy.py:150`).
3. Upstream робіць эфект, але на адказе таймаўт/памылка: `MCPUpstream.call` кідае `RuntimeError` (`upstream.py:104-113`, таймаўт — `upstream.py:108-110`).
4. Выключэнне пралятае паўз `receipt2 = self.registry.append(...)` (`proxy.py:151-156`) → запіс `exec_hash` **не створaны**.

**Чакаемы эфект:** дзеянне перасекла мяжу, але ланцуг не мае запісу «выканана» — толькі «дазволена». Нельга адрозніць «дазволена і выканана» ад «дазволена і не выканана». Абяцанне «запіс пра тое, што адбылося» парушана менавіта там, дзе яно найпатрэбнейшае.

**Доказ:** `proxy.py:128` (decision-receipt да выканання) vs `proxy.py:150-156` (exec-receipt пасля); `upstream.py:104-113` (кідае на таймаўце). Тэст-суіт лічыць «executed» па `exec_hash` (`scripts/security_boundaries.py:139-144`) — пры памылцы там нічога няма.

**Тэст, які гэта даказвае:** `test_upstream_error_still_records_attempt_and_writes_exec_receipt`.

---

### V7 · Адкліканне не даходзіць да выкліку ў палёце — **OPEN**

**Сцэнар:**
1. Выклік праходзіць гэйты: `decision = allow` (`proxy.py:121`).
2. У іншай тэрэдзе прылятае `POST /revoke` → `agent.state = "halted"`, `warrant.state = "revoked"` (`proxy.py:161-171`).
3. Першая тэрэда спакойна даходзіць да `self.upstream.call(...)` (`proxy.py:150`) — ніякай другой праверкі стану паміж рашэннем і выкананнем няма, супольнага lock няма.

**Чакаемы эфект:** «апошні выклік пасля revoke» выконваецца (kill-latency K7 у `security_boundaries.py:305-330` мерае *наступны* выклік, не той, што ўжо ў палёце). Акрамя таго, агенту, які ўжо ведае endpoint upstream, вузел не патрэбны зусім — ён можа зваць upstream наўпрост, у абыход усяго кантролю (гэта архітэктурнае, не дэфект кода, але абяцанне «мяжа — пункт кантролю» трымаецца толькі калі ўвесь трафік ідзе праз вузел).

**Доказ:** `proxy.py:121` (рашэнне) → `proxy.py:150` (выкананне) без проміжнай праверкі; `proxy.py:161-171` (`revoke` без сінхранізацыі з `intercept`); `upstream.py:77-113` (прымы MCPUpstream, які можна зваць наўпрост).

**Тэст, які гэта даказвае:** `test_revoke_blocks_call_already_past_the_gate`.

---

### V8 · DoS на кантролер спыняе ўвесь бізнес — **UNKNOWN**

**Сцэнар:** `/mcp` не мае ні rate-limit, ні чаргі, ні backpressure; `intercept` на кожным `allow` робіць сінхронны `fsync` запісу (`registry.py:47`) і блакуючы паход у upstream (`proxy.py:150`). Паток дробных выклікаў нацягвае тэрэдpool → усе агенты стаяць.

**Доказ:** `api.py:206-237` (без middleware/лімітаў), `registry.py:44-47` (fsync у крытычным шляху), `proxy.py:150` (блакуючы выклік у сінхронным request-хэндлеры).

**Статус:** UNKNOWN — няма ні тэста, ні заяўленай мяжы. Патрабуе эмпірычнай праверкі пад нагрузкай, таму не пазначаю OPEN.

---

## 2. Вектары, закрытыя кодэм

### C1 · «Свой» агент у рэестры — **CLOSED**
Рэестр актораў аб'яўлены ў кодзе, API рэгістрацыі няма: `actors.py:130-160` (`ACTOR_SEED`), `api.py` не мае `POST /actors`. Дадаць актора можна толькі змяніўшы рэпазіторый. Ліміт — уласцівасць актора, правяраецца да warrant (`plugins/actor_scope.py:9-14`).

### C2 · Подмена загада пасля подпісу — **CLOSED**
Палітычны рухавік пераправярае подпіс *да* чытання правілаў: `policy.py:72-79` (`order_ok`, fail-closed на любы выключэнне), `policy.py:87-90`, `warrants.py:40-41` (`compare_digest`). Dev-прылада `/_dev/tamper` (`api.py:313-338`) менавіта гэта і дэманструе.

### C3 · Break-glass як шчыліна (іншы tool / пераадоленне irreversible) — **CLOSED**
Грант матчыцца па `tool` дакладна і па `cls`: `breakglass.py:101-107`. `irreversible`/`authorize` непераадольныя: `breakglass.py:40` (`UNLIFTABLE`), `breakglass.py:68-70`, `breakglass.py:101-102`. Клас-флор накладаецца *пасля* пад'ёму і не апускаецца: `plugins/order_policy.py:17-33`, `actions.py:169-171`.

### C4 · Клас не можа апысціць рашэнне — **CLOSED**
`actions.py:103-104` (`_RAISE`), `actions.py:169-171` — клас толькі падвышае (allow→human/deny), ніколі не паніжае deny/revoked.

### C5 · Рэдагаванне/выдаленне радка ланцуга — **CLOSED** (акрамя V2)
`registry.verify` вяртае `broken_at`: `registry.py:62-70`, паказана J6/J7 у `scripts/security_boundaries.py:152-168`. Consistent-rewrite закрыты anchor'ам: `anchor.py:63-80`, A3-A5 у `security_boundaries.py:280-310` — падробіць anchor без ключа нельга. **Але** гэта не закрывае V2 (`/reset`) і `anchors.jsonl` у тым жа каталозе, што і `receipts.jsonl` (`config.py:33-36`) — «фізічнае раздзяленне» толькі калі `WARRNT_ANCHOR` паказвае па-за вузлом.

### C6 · Ключ issuer у памяці/на дыску — **CLOSED (з заўвагай)**
Ключ не трапляе ў payload/запіс/лог: `warrants.py:3-4,37-51`. Файл `0600`: `warrants.py:30-34`. Але ён ляжыць у тым жа каталозе `state/` (`config.py:34`): хто мае доступ да хоста — мае ключ, а значыць можа падпісаць і загад, і anchor (`anchor.py:6-14` гэта прызнае); абарона ад host-уладальніка не заяўлена.

---

## 3. Агульны падлік

| Статус | Колькасць | Вектары |
|---|---|---|
| OPEN | 7 | V1, V2, V3, V4, V5, V6, V7 |
| UNKNOWN | 1 | V8 |
| CLOSED | 6 | C1–C6 |

Тры найвострыя: **V2** (адзіны `POST /reset` робіць `receipts.jsonl` пустым, а `verify`+`anchor` зялёныя — сведчанні знішчаны пад подпісам), **V1** (увесь control plane бяз-аўтэнтыфікаваны: ананімны `break-glass` граб выдаецца любым), **V3** (значэнні PII ляжаць у самім hash-ланцугу і аддаюцца праз `GET /receipts`).

---

## 4. Топ-5 тэстаў на заўтра

1. `test_reset_cannot_erase_history` — ламае V2: `POST /reset` не павінен даваць `verify ok=True length=0`; гісторыя альбо захоўваецца, альбо пазначаецца як «evidence destroyed», а anchor не павінен зелянець на GENESIS.
2. `test_control_plane_requires_auth` — ламае V1: усе мутацыйныя эндпоінты (`/reset`, `/revoke`, `/api/breakglass*`) без крэдэнталаў → 401/403.
3. `test_receipt_never_stores_pii_values` — ламае V3: пасля `redact`-выкліку вядомыя значэнні PII не сустракаюцца ў `/receipts`.
4. `test_upstream_error_still_records_exec_receipt` — ламае V6: upstream кідае таймаўт пасля выканання → у ланцугу ўсё роўна павінен быць запіс спробы/выканання.
5. `test_breakglass_single_use_under_concurrency` — ламае V5: N адначасовых выклікаў з адным грабам даюць роўна 1 `executed`.
