# 前端重構規格

這份規格是雲端下載器前端重構（含必要的後端 API 調整）的定案版本，結合原始需求與階段 0 盤點後確認的修改。每個階段開始前先重新讀取本檔。本檔與程式碼不一致時，先提出來確認，再修正其中一方。

## 背景

- 專案：從雲端分享連結下載檔案的工具。前端 Vite + React + TypeScript，後端 FastAPI。
- 部署：自架在 NAS，少數人透過區網或 VPN 使用，不對外開放、沒有登入機制。所有人共用同一份任務清單與設定。
- 下載方式：由後端下載並存到 NAS 磁碟，位置限定在後端設定的根目錄（`DOWNLOAD_DIR`）之內。
- 支援的雲端：只有 Keep2Share（`k2s.cc`、`keep2share.cc`）。通用的直連 provider 已移除，任何不屬於支援雲端的網址一律拒絕。
- 主要裝置：桌機。
- 介面語言：以 i18n 支援繁體中文（`zh-Hant-TW`，預設）與英文（`en`），見「多語系」。
- 產品名稱未定：集中在前端的單一常數 `APP_NAME`（`web/src/app-name.ts`），暫定值 `Downloader`。頁面標題與名稱標誌都從這裡讀取；`vite.config.ts` 以 `transformIndexHtml` 把它寫進 `<title>`。

## 工作方式

- 在 branch `feat/zh-dashboard-refactor`（從 `main` 分出）進行。每個階段結束時執行 `python3 script/check.py` 與 `python3 script/check_conventions.py --staged`，交給全新 context 的 `code-reviewer` 審查，commit，然後停下來回報：改了什麼、如何驗證、還有哪些未解決的問題。收到確認前，不進入下一階段。
- 規格沒寫到、或規格與現有程式衝突時，先提出來問，不自行假設。
- commit 訊息與程式註解沿用 repo 慣例：英文、Conventional Commits、無 emoji、無 trailer。
- 推送、建立 PR 前需要明確同意；合併由人執行。
- 階段順序：0 盤點與提案（已完成）→ 1 後端 API → 2 前端 → 3 續傳強化。

## 階段 0 盤點結果

- 前端：React 19、Vite 8、TypeScript 6、oxlint。沒有路由、狀態管理、UI 套件與測試工具。單頁，每秒輪詢 `/api/jobs`，單一全域 CSS。
- 後端：任務在記憶體 `JobManager.jobs`，持久化到 `DATA_DIR/jobs.json`（在 `file_lock` 下原子寫入）。一個任務一個執行緒，`MAX_ACTIVE_JOBS` 控制同時下載數。引擎是多連線分段下載，必須取得 206，分段檔在 `DATA_DIR/jobs/<id>/partNNNNN`，本來就能續傳。單一 uvicorn process。
- 設定：沒有設定頁與設定 API，只有環境變數。
  - (a) 設定 API 回傳 token 或 cookie 明文：不成立，專案沒有 token 或 cookie。
  - (b) 下載目錄限制在根目錄內：大致成立，有缺口。檔名經 `safe_filename` 化為單一路徑元件，`/file` 以 `resolve()` 後檢查位於根目錄內。缺口：`unique_path` 用 `exists()`，懸空的符號連結會被當成不存在；組合用的暫存檔以 `open("wb")` 開啟，會跟隨符號連結。
- 部署：正式環境由 FastAPI 以 `StaticFiles(html=True)` 提供 `web/dist`，沒有 SPA fallback，repo 內沒有反向代理。

## 階段 1：後端 API

### 安全與基礎

- 網址白名單：網址是否屬於支援的雲端，一律由後端再驗證一次，解析與建立任務時都要驗證。前端驗證只是使用體驗，可以被繞過。不支援的網址直接拒絕，避免 NAS 被用來存取任意位址（SSRF）。
- 路徑安全：
  - 檔案相關操作一律以任務 ID 定位，API 不接受路徑參數。任務 ID 在路由驗證為 `^[0-9a-f]{12}$`。
  - 所有實際路徑都先解析成真實路徑，再確認位於根目錄之內；提供或刪除檔案時拒絕符號連結。
  - `unique_path` 把符號連結（包含懸空的）視為已存在；暫存檔以 `O_CREAT | O_EXCL | O_NOFOLLOW` 建立。
- 根目錄：由環境變數 `DOWNLOAD_DIR` 指定，不能從介面修改，設定頁只顯示。
- 未完成的檔案：下載中的資料在 `DATA_DIR/jobs/<id>/` 的分段檔；組合時寫入 `DOWNLOAD_DIR/<name>.part`，完成後才改成正式檔名，透過 SMB 瀏覽的人不會拿到不完整的檔案。改名不覆蓋任何既有檔案。
- 合併與檢查影片期間（`phase` 為 `assembling` 或 `verifying`），暫停、取消、刪除一律以 `invalid_state` 拒絕。
- 檔名衝突：自動改名為 `name (1).ext`（沿用 `unique_path`）。
- 任務持久化：沿用 `DATA_DIR/jobs.json`（在 `file_lock` 下原子寫入），不改用 SQLite。舊的 `jobs.json` 要能載入並對應到新狀態。
- 後端重啟：原本進行中的任務改為「已暫停」，保留分段檔，可以繼續（沿用現有行為）。階段 3 再依 `resumable` 細分。
- 驗證碼：只用 OCR，不再請使用者手動輸入。每個任務的每次執行最多嘗試 `CAPTCHA_MAX_ATTEMPTS` 次（環境變數，預設 50；重試會重新計算），超過就以 `captcha_failed` 失敗。移除 `CaptchaPanel`、兩個驗證碼端點、`awaiting_captcha` 狀態與 `CAPTCHA_OCR` 環境變數。
- SSE 的前提：
  - 只跑單一 uvicorn worker，因為任務狀態與執行緒都在該 process 的記憶體裡。把這項限制寫進 README。
  - 回應標頭加 `X-Accel-Buffering: no` 與 `Cache-Control: no-cache`，避免反向代理緩衝。
  - 每 15 秒送一次心跳註解。
  - 同一任務的進度事件每秒最多 2 次；狀態改變立即送出，並帶上最新進度。
  - 事件從工作執行緒以 `call_soon_threadsafe` 放入每個訂閱者的有界佇列；佇列滿時中斷該連線，由前端重連並重新取得完整清單。
  - 連線中斷由心跳寫入失敗偵測，不另外輪詢。
- SPA fallback：`/api` 以外的未知路徑回傳 `index.html`，存在的靜態檔照常提供；未知的 `/api/*` 回傳 JSON 404。
- 開發環境用 Vite proxy 轉送 `/api`，不處理 CORS。
- 同時下載數可在執行期調整，以 `Condition` 實作可變大小的名額取代 `Semaphore`。

### 設定

- 設定存在 `DATA_DIR/settings.json`，只在 `file_lock` 下寫入。環境變數提供初始預設值。
- 欄位：`connections`（1 到 64）、`split_size`（至少 20 MiB）、`use_proxies`、`max_active_jobs`。另外唯讀回傳 `download_root`。
- 新任務建立時套用當下的設定。首頁不再提供每筆任務的選項（另存檔名、連線數、分段大小）。

### 任務狀態

- `status` 只有 6 種：`queued`、`downloading`、`paused`、`completed`、`failed`、`canceled`。
- 內部的細節階段一律屬於 `downloading`，以 `phase` 區分：`resolving`、`captcha`、`waiting`（所有 IP 都在冷卻時的倒數）、`links`、`downloading`、`assembling`、`verifying`。
- 說明文字以翻譯鍵表示：`message_key`（例如 `messages.captcha_attempt`）與 `message_params`（例如 `{ "n": 3 }`）。`message` 是依繁中翻譯檔產生的備援文字，前端只在找不到翻譯鍵時顯示。
- 錯誤一律是 `{ code, key, params, message }`：`code` 是穩定的機器代碼，`key` 是翻譯鍵（通常是 `errors.<code>`，同一代碼可有變體，例如 `errors.quota_exceeded_wait`），`params` 是插值參數，`message` 是繁中備援。原始例外字串只寫入 log，不送到前端。
- 冷卻倒數以參數傳送秒數（`{ "seconds": 125 }`），由前端依語系格式化。

### 錯誤代碼

- 解析：`invalid_url`、`unsupported`、`not_found`、`private`、`premium_only`、`quota_exceeded`、`upstream_error`。
- 任務：另有 `captcha_failed`、`links_expired`、`stalled`、`disk_full`、`internal_error`；階段 3 加入 `remote_changed`、`range_unsupported`。
- 建立任務：`duplicate_active`、`duplicate_completed`（兩者都附 `task_id` 與 `task_status`）、`insufficient_space`。
- 其他：`task_not_found`、`invalid_state`（動作不適用於目前狀態）、`file_missing`、`invalid_request`（格式錯誤）、`invalid_settings`、`not_found`（未知的 API 路徑，包含 `/api` 本身）、`method_not_allowed`、`http_error`。
- `ProviderError` 帶 `code` 屬性。

### 端點

API 路徑由 `/api/jobs` 改為 `/api/tasks`；後端內部名稱維持 `Job`。

- `GET /api/providers`：provider 清單。
  - 欄位：`id`、`name`、`icon`（前端對應圖示用的識別碼）、`patterns`（網址比對規則）。
  - 規則只用 Python 與 JavaScript 都支援的正規表達式子集：不用具名群組、lookbehind、inline flags。檔案 ID 放在第一個擷取群組。比對前先把 scheme 與 host 轉成小寫。
  - 共用測試資料 `shared/provider-test-cases.json`：每筆為 `{ url, provider, file_id }`，不支援的網址 `provider` 與 `file_id` 為 null。後端 pytest 與前端 Vitest 都跑同一份。
- `POST /api/resolve`，body `{ url }`：解析分享連結，不建立任務。
  - 先以白名單比對，再向上游取得檔案資訊（k2s `getFilesInfo`）。
  - 成功時回傳：`provider`、`file_id`、`file_name`、`size`（未知時為 null）、`resumable`、`duplicate`、`free_bytes`、`required_bytes`。
  - `required_bytes`：下載這個檔案需要的空間（見建立任務的空間檢查），大小未知時為 null。前端以它和 `free_bytes` 比較，判斷空間是否足夠。
  - `duplicate`：同一檔案已有任務時為 `{ task_id, status }`，否則為 null。
  - 失敗時回傳 4xx 與 `{ code, key, params, message }`。
- `GET /api/tasks`：任務清單，新的在前。每筆欄位：
  - 識別：`id`、`provider`、`file_id`、`file_name`
  - 進度：`size`、`bytes_done`、`speed`（bytes/s，移動平均）、`eta`（秒，未知時為 null）
  - 狀態：`status`、`phase`、`message_key`、`message_params`、`message`、`resumable`、`file_exists`、`error`（`{ code, key, params, message }` 或 null）、`verified`（影片檢查結果 `ok`、`corrupt` 或 null）
  - 時間：`created_at`、`completed_at`
- `POST /api/tasks`，body `{ url, force }`：建立任務。
  - 同一檔案已有 `queued`、`downloading`、`paused`、`failed` 或 `canceled` 的任務時，一律以 409 `duplicate_active` 拒絕，並附上既有任務 ID（前端提供前往查看或重試）。
  - 已完成過的檔案，需要 `force: true` 才建立，否則回 409 `duplicate_completed`。
  - 已知大小時，建立前再檢查一次剩餘空間，不足就以 `insufficient_space` 拒絕。`DATA_DIR` 與 `DOWNLOAD_DIR` 在同一個檔案系統時，組合期間需要兩倍空間，以 `2 x size` 檢查；不同檔案系統時分別檢查。
- `POST /api/tasks/{id}/pause`：停止下載，保留分段檔與已下載位元組數。
- `POST /api/tasks/{id}/resume`：已暫停的任務重新排隊，從已下載的位置繼續。
- `POST /api/tasks/{id}/cancel`：取消，狀態改為 `canceled`，刪除分段檔與 `.part` 檔。
- `POST /api/tasks/{id}/retry`：失敗或已取消的任務重新排隊。
- `DELETE /api/tasks/{id}?delete_file=true|false`：移除紀錄。
  - `delete_file=true` 時，同時刪除 NAS 上的檔案。
  - 進行中的任務先取消再移除。
- `POST /api/tasks/clear-completed`：移除所有已完成任務的紀錄，不刪檔案。
- `GET /api/tasks/{id}/file`：把已完成的檔案下載到使用者電腦。
  - 支援 Range（Starlette `FileResponse` 內建）。
  - `Content-Disposition` 以 RFC 5987 格式（`filename*=UTF-8''…`）處理中文檔名。
  - 檔案已不存在時回 404，並把該任務的 `file_exists` 設為 false。
- `GET /api/storage`：下載根目錄所在檔案系統的 `free_bytes`、`total_bytes`。
- `GET /api/settings`、`PUT /api/settings`：讀寫設定。
- `GET /api/events`：SSE。事件類型：
  - `task`：新增或更新，內容為完整任務物件。
  - `task_removed`：`{ id }`。
  - `storage`：剩餘空間變化時送出，最多每 5 秒一次。
- 資料模型預留續傳欄位：`etag`、`last_modified`。

### 部署文件

- README 說明只能跑單一 worker，以及服務沒有登入、只能讓區網或 VPN 存取。
- `compose.yaml` 的對外綁定位址改為 `${BIND_ADDR:-127.0.0.1}:8000`，由 `.env` 設定。

### 驗收

pytest 覆蓋：
- provider 比對（共用測試資料）
- resolve 的錯誤對應（上游以 mock 取代）
- 任務生命週期：建立、暫停、繼續、取消、重試、刪除、清除已完成、重啟後的狀態
- 檔案端點的 Range 與中文檔名
- 路徑限制（`..` 與符號連結）
- SSE 的標頭、心跳與節流

## 階段 2：前端

### 套件

| 套件 | 處理 | 理由 |
| --- | --- | --- |
| react、react-dom、vite、@vitejs/plugin-react、typescript | 保留 | 已是現行版本，已用 TypeScript |
| oxlint | 保留，把 lint 加進 `check.py` | 已存在且快 |
| `react-router` v7（宣告式模式） | 新增 | 三個路由，以 `?focus=<id>` 捲動到指定任務 |
| `@tanstack/react-query` v5 | 新增 | query key、AbortSignal、以 `setQueryData` 接收 SSE |
| `radix-ui`（只用 Dialog、Tooltip、Checkbox、VisuallyHidden） | 新增 | 無樣式，處理焦點與 ARIA。不使用 shadcn/ui，不帶預設外觀 |
| `@fontsource-variable/archivo` | 新增 | 自架字型。安裝時確認包含 wdth 軸，沒有就回報 |
| `i18next`、`react-i18next`、`i18next-browser-languagedetector` | 新增 | 多語系：插值、語系偵測與切換 |
| `vitest`、`jsdom`、`@testing-library/react`、`@testing-library/user-event` | 新增（dev） | 目前沒有前端測試 |

- 樣式：純 CSS。`styles/tokens.css` 定義所有顏色變數，各元件用 CSS Modules。選擇器以單一 class 為主，重設樣式包在 `:where()` 裡，避免權重互相抵銷。
- 通知：沿用自製的 `Toasts`，重新設計樣式。
- `check.py` 加入 `npm --prefix web run lint` 與 `npm --prefix web test`。

### 資訊架構

- 三個路由：`/` 下載（首頁）、`/tasks` 檔案狀況、`/settings` 設定。
- 頂部導覽列：左側是三個分頁，右側顯示「NAS 剩餘 X」，依大小自動用 GB 或 TB。
- 首頁：
  - 中央是名稱標誌與輸入插槽。
  - 解析成功時，插槽下方出現預覽區。
  - 再往下是最近 5 筆任務與「查看全部」。點擊任務會跳到 `/tasks`，捲動到該筆並短暫標示。
  - 沒有任何任務時，不顯示最近任務區塊。
- 檔案狀況：高密度表格。
  - 欄位依序為：狀態（燈號加文字）、雲端、檔名、大小、進度、速度、剩餘時間、操作。
  - 狀態文字在 `downloading` 時依 `phase` 顯示細節，例如「解驗證碼（第 3 次）」「等待冷卻 12:30」。
  - 表格上方有狀態篩選（全部、進行中、已完成、失敗）與「清除所有已完成」。
- 設定：連線數、分段大小、使用公開代理、同時下載數可編輯（存到後端，所有人共用）；下載根目錄只顯示；語言只存在這個瀏覽器。
- 寬度小於 768px 時，表格每列改成兩行排列。只保證可以操作，不另外設計手機互動。

### 輸入與解析

- 輸入框只接受單一網址，但不攔截鍵盤輸入：允許自由輸入，自動去除前後空白，即時顯示驗證狀態。
- 貼上時，若文字中恰好有一個網址，自動取出；超過一個則提示「一次只能貼一個連結」。
- 全域貼上：在首頁任何位置按 Ctrl/⌘+V（焦點不在其他輸入框時），都貼進輸入框。做法是監聽 `paste` 事件，不使用剪貼簿 API，因為區網 HTTP 不是安全環境，瀏覽器不開放剪貼簿 API。
- 拖放：支援把連結拖放進輸入框（`text/uri-list`）。
- 解析流程：
  1. 先用 provider 清單在前端比對。清單只載入一次。
  2. 格式正確後呼叫 `/api/resolve`：貼上時立即呼叫；手動輸入則在停止輸入 400ms 後呼叫。
  3. 以正規化後的網址作為 query key。過期的請求用 AbortSignal 取消，較早的請求晚回來時，不能覆蓋較新的結果。
- 預覽區顯示雲端圖示、檔名、大小、NAS 剩餘空間：
  - 空間不足：停用下載，並說明還差多少空間。
  - 大小未知：標示「大小未知」，並停用下載。目前的分段下載需要檔案大小；Keep2Share 一律回報大小，這個狀態只在上游資料異常時出現。
  - `duplicate` 是未完成的任務（排隊、下載中、已暫停）：不能下載，提供「前往查看」。
  - `duplicate` 是失敗或已取消的任務：不能下載，提供「重試」與「前往查看」。
  - `duplicate` 是已完成的任務：提示已下載過，提供「仍要下載」（送出 `force: true`）。
- 解析失敗時，依錯誤的 `key` 與 `params` 顯示對應文案與下一步。
  - 文案都在翻譯檔裡，找不到翻譯鍵時才顯示後端的 `message`。
  - 絕不顯示原始例外字串。
- 鍵盤：預覽成功時按 Enter 開始下載，按 Esc 清空。送出成功後清空輸入框並保留焦點。
- 輸入插槽右側的燈：
  - 空白時不亮（只有鐵灰外框）
  - 解析中：琥珀
  - 可下載：綠
  - 無法下載：紅

### 即時更新

- 整個 App 只建立一條 EventSource 連線，放在最上層。收到事件後，用 `setQueryData` 更新 TanStack Query 的快取。
- 每次連線建立時（包括自動重連），重新取得完整任務清單，補上斷線期間漏掉的事件。
- 任務完成或失敗時，顯示頁內通知。
- 有進行中的任務時，分頁標題顯示 `(n) {APP_NAME}`。
- 不使用瀏覽器系統通知，因為它需要 HTTPS。

### 狀態頁操作

- 每列的操作：暫停、繼續、取消、重試、下載到電腦、刪除。
  - 暫停只在 `queued` 或 `downloading` 且 `resumable` 為 true 時顯示；繼續只在 `paused` 時顯示。
  - 下載到電腦僅限已完成且 `file_exists` 為 true 的任務。
  - 圖示按鈕都要有 `aria-label` 與工具提示。
- 刪除時開啟對話框，內含「同時刪除 NAS 上的檔案」核取方塊，預設不勾選。
- `file_exists` 為 false 的已完成任務，顯示「檔案不存在」並停用下載鍵。

### 視覺設計：黑色機殼

概念取材自 NAS 機殼的前面板：狀態用指示燈表示，輸入框是面板上唯一有厚度的插槽。全頁只有插槽這一個強烈的元素，其他地方保持平整、安靜。

色彩全部定義為 CSS 變數，以用途命名。目前只做深色，但要讓日後加淺色主題時，只需補一組變數值。
- 機殼 `#202428`：頁面底色
- 面板 `#2A2F34`：導覽列、預覽區、表頭、對話框
- 插槽 `#15181B`：輸入插槽、進度條軌道等凹陷元素
- 刻字 `#E4E7E4`：主要文字
- 鐵灰 `#9097A0`：次要文字、已暫停燈號
- 分隔 `#2F3439`：表格列的分隔線
- 琥珀燈 `#F0A03A`：下載中、鍵盤焦點框、唯一的主要按鈕（按鈕上的文字用 `#1B1E21`）
- 綠燈 `#3DBA6F`：已完成、可下載
- 紅燈 `#EE6A61`：失敗、錯誤訊息

琥珀色只用在上面列的三種用途。目前所在的分頁用刻字色的 2px 底線標示。

燈號（旁邊一律附文字，不只靠顏色傳達）：
- 排隊中：空心琥珀
- 下載中：實心琥珀
- 已暫停：實心鐵灰
- 已取消：空心鐵灰
- 已完成：綠
- 失敗：紅

字體：
- Archivo：
  - 可變字體，需包含寬度軸（wdth）。以 npm 套件（Fontsource）自架，不從 Google Fonts CDN 載入。
  - 用於名稱標誌（寬度 125%、字重 500）與所有數字（`font-variant-numeric: tabular-nums`）。
- 其他文字（含中文）用系統字體：`system-ui, "PingFang TC", "Microsoft JhengHei", "Noto Sans TC", sans-serif`。
- 名稱標誌直接以文字排版，並預載 Archivo 字型檔（由 `vite.config.ts` 注入 `<link rel="preload">`），避免首頁閃爍。
- favicon 用「插槽加一顆琥珀燈」的簡單 SVG 圖形，不依賴名稱。

插槽：底色用插槽色。1px 邊框上緣較深（`#0E1012`）、下緣較淺（`#3A4046`），做出凹陷感，不使用 box-shadow。

動態：全頁只有一個過場動畫。
- 解析成功時，預覽區從插槽下方滑出，約 200ms，ease-out。
- `prefers-reduced-motion` 時直接顯示。
- 其他地方不加入場動畫或 hover 動畫。

避免：
- 全大寫的英文標籤
- 等寬字體的資料標籤
- 用「·」串接資訊
- 在連結或按鈕文字後加「→」
- 所有東西都做成圓角卡片
- 裝飾性的漸層與陰影

版面：首頁內容置中，最大寬度約 560px；狀態頁最大寬度約 1200px，表格靠左對齊。

文案（兩種語言都適用）：
- 英文用句首大寫（sentence case），不用全大寫或每字大寫；不用 "please"、"successfully"。
- 按鈕以動詞開頭，同一個動作在整個流程用同一個詞（按鈕「下載」對應通知「已開始下載」）。
- 錯誤訊息要說明發生了什麼事、該怎麼處理。例如「這個檔案需要權限才能下載。把分享設定改為『知道連結的人皆可檢視』後再試一次。」不道歉，不加「錯誤：」前綴。
- 空狀態是邀請：狀態頁沒有任務時，顯示「還沒有下載任務」與前往下載頁的連結。
- 輸入框的 placeholder 用真實的範例網址。
- 不用「成功」「請」這類贅字。

品質底線：
- 鍵盤可以完成所有操作，焦點清楚可見。
- 文字對比至少達到 WCAG AA。
- 狀態頁使用真正的 `<table>`。
- 注意 CSS 選擇器的權重，避免樣式互相抵銷。

### 多語系

- 使用 i18next 與 react-i18next。支援 `zh-Hant-TW`（預設）與 `en`。
- 翻譯檔：
  - 介面文字：`web/src/locales/zh-Hant-TW.json`、`web/src/locales/en.json`。
  - 後端訊息與錯誤：`shared/i18n/zh-Hant-TW.json`、`shared/i18n/en.json`，分為 `messages` 與 `errors` 兩個命名空間。後端以繁中檔產生備援 `message`，前端合併兩份翻譯檔使用。
  - 插值一律用 i18next 的 `{{name}}` 語法。
- 語系決定順序：使用者在設定頁的選擇（存在該瀏覽器的 `localStorage`，每人各自設定，不影響他人），其次是瀏覽器語言（`zh` 開頭用 `zh-Hant-TW`，其他用 `en`）。
- 切換語系時，`<html lang>` 一併更新。
- 數字、大小、速度、時間依語系以 `Intl` 格式化；數字仍用 Archivo 與 `tabular-nums`。
- 設定頁新增「語言」欄位；它是瀏覽器端設定，不送到後端。

### 驗收

- pytest：後端用到的每個翻譯鍵都存在於兩份 `shared/i18n` 翻譯檔，且兩種語言的插值參數相同。
- Vitest：
  - 兩份介面翻譯檔的鍵與插值參數一致
  - 網址擷取與 provider 比對（共用測試資料）
  - resolve 的延遲呼叫與過期請求處理
  - SSE 事件更新快取的邏輯
- 以 `playwright-cli` 在 1280px 與 375px 寬度檢查。手動驗證清單：
  - 貼上各種連結
  - 空間不足
  - 重複檔案
  - 下載中重新整理頁面
  - 後端重啟後，SSE 自動重連並補齊清單

## 階段 3：續傳強化

暫停、繼續與重啟後改為已暫停，在階段 1 已提供。這個階段補上正確性檢查：

- 繼續前重新解析分享連結、清除舊的直連網址並重新產生，因為直連網址有時效。
- 分段請求帶 `Range` 與 `If-Range`（優先用 ETag，沒有時用 Last-Modified）。
- 對可續傳的任務，上游回 200 而不是 206，代表遠端檔案已變更。此時捨棄分段檔、從頭下載一次，並在任務列顯示「遠端檔案已變更，已重新下載」。
- `resumable` 依實際回應判斷（`Accept-Ranges` 或 206 回應），不只依 provider 推測。上游不支援 Range 時，任務以 `range_unsupported` 失敗，`resumable` 為 false；不另外實作單一連線的備援下載。
- 後端重啟時，可續傳的進行中任務改為「已暫停」；不可續傳的改為「失敗」，錯誤原因為「服務重新啟動，下載中斷」，可以重試。
- 前端：`resumable` 為 true 時才顯示暫停與繼續；不可續傳的任務只有取消。
- 檔案端點的檢查與開檔之間有空窗：有 SMB 寫入權限的人可以在檢查通過後，把檔案換成符號連結，讓伺服器送出它讀得到的任意檔案（包含 `DATA_DIR/proxies.user.txt` 的代理帳密）。改為以 `O_NOFOLLOW` 開檔後 `fstat` 驗證，並自行從該檔案描述元提供 Range 回應。
- 需執行期檢查（Keep2Share）：
  - CDN 直連是否回傳 `ETag` 或 `Last-Modified`。
  - 同一檔案不同次產生的直連，ETag 是否相同（決定 If-Range 能否跨越直連重新產生）。
  - `getFilesInfo` 用哪些欄位表示私人與付費限定檔案（`access`、`is_available`）。
- 驗收：pytest 模擬以下情境（擴充 `tests/conftest.py` 的 Range 伺服器，可控制 ETag、Range 支援與內容）：
  - 支援與不支援 Range 的上游
  - 續傳時遠端檔案已變更
  - 暫停期間後端重啟
