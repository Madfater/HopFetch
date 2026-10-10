# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

One person: the operator who runs the NAS. They use it mostly from a desktop browser on the LAN or over VPN. The server has no login, and anyone who can reach it shares the same task list and settings, but in practice the operator is the only user.

## Product Purpose

Hop fetch downloads files from file hosting platforms onto a NAS. The user pastes a link, walks away, and later finds a finished file in the download folder. They never have to deal with captchas, IP cooldowns, proxies or broken connections themselves. Most visits are short: drop a link, or check on progress for a moment.

Success means the file shows up complete and correct under its real name, and the user never has to step in unless something truly needs a decision, such as a failed task to retry.

## Positioning

Free Keep2Share links normally give one rate-limited connection, sit behind an image captcha, and make an IP wait between downloads. Hop fetch solves the captcha with offline OCR. It turns one free download key into many links and fetches byte ranges over them in parallel into resumable part files. It waits out cooldowns with a visible countdown. MEGA public links get the same multi-connection engine, with decryption and an integrity check at assembly. All of this runs headless on the user's own NAS, with nothing to install on the client.

## Operating Context

- Self-hosted in Docker on a NAS and deployed through Arcane. The app is reached at port 8000 on the LAN or over VPN. It is never exposed to the internet.
- Finished files land in `DOWNLOAD_DIR`, and the user often browses that folder over SMB. While a file is being assembled it is named `<name>.part`, so SMB never shows a partial file under its real name.
- Jobs survive server restarts and resume where they stopped, on their own unless the user paused them, with a note that the server restarted.
- The dashboard has three routes: Download (paste and check a link), Downloads (tasks and their progress; 下載清單 in Chinese) and Settings. Updates are pushed live over server-sent events.

## Capabilities and Constraints

- Providers: Keep2Share (`k2s.cc`, `keep2share.cc`) free links and MEGA (`mega.nz`) public file links. Every other URL is rejected by the backend allowlist.
- Task statuses: `queued`, `downloading`, `paused`, `completed`, `failed`, `canceled`. While downloading, the phases are `resolving`, `captcha`, `waiting`, `links`, `downloading`, `assembling` and `verifying`.
- Pause, cancel and delete are refused during `assembling` and `verifying`.
- Editable settings: connections (1 to 64), split size (at least 20 MiB), public proxies on or off, and max active jobs. The download root is shown read-only.
- Each download carries a proxy choice, a switch in the Download page's preview that the browser remembers. Off, the task connects directly.
- Errors reach the UI as translation keys with parameters. Raw exception text never does.
- A single uvicorn worker. There is no authentication and no per-user state.
- The backend is FastAPI. The frontend is Vite, React 19 and TypeScript with Radix primitives and CSS modules.

## Brand Commitments

- The name is "Hop fetch". It is defined only in `web/src/app-name.ts`.
- The interface languages are Traditional Chinese (`zh-Hant-TW`, the default) and English. The browser language decides, and a language menu in Settings overrides it per browser. All copy has to work in both.
- The interface is dark-only, and that is deliberate. Do not add a light theme.

## Evidence on Hand

No testimonials, users, benchmarks or press exist, and none should be invented. Real speeds and behavior come from live tasks only.

## Product Principles

- Unattended by default. Every wait, retry and recovery the app can handle on its own, it handles without asking.
- Show state, not mechanics. The user needs to know where a file is and whether anything needs them. Connection counts and proxies are secondary detail.
- Never lose bytes. Pausing, restarting and failing all keep finished work resumable. The UI should never imply otherwise.
- Built for one person. Prefer fewer controls with sensible defaults over options aimed at an audience that does not exist.
