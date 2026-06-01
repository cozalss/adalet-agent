# Frontend Test Rehberi

> ADALET web arayüzünün otomatik test altyapısı. **Vitest** (jsdom) tabanlı;
> saf mantık, React hook'ları ve bileşen render'ı birim testlerle kaplanır.
> Felsefe (gstack "real, not mocked"): mantık birim testlerle, büyük entegrasyon
> akışları gerçek tarayıcı QA ile (Playwright) doğrulanır.

## Çalıştırma

```bash
cd frontend
pnpm test            # tüm testleri bir kez koş (CI ile aynı)
pnpm test:watch      # geliştirirken izle
pnpm test:coverage   # kapsam raporu (text + html + json-summary)
```

Kapsam HTML raporu: `frontend/coverage/index.html` (gitignore'da).

## Araçlar

| Araç | Amaç |
|------|------|
| **Vitest 4** | Test koşucusu (Vite config'i paylaşır, hızlı) |
| **jsdom** | Tarayıcı ortamı (localStorage, atob, TextDecoder, DOM) |
| **@testing-library/react** | `renderHook` — hook'ların durumsal davranışı |
| **react-dom/server** | `renderToStaticMarkup` — bileşeni HTML'e basıp doğrula (ek dep yok) |
| **@vitest/coverage-v8** | Kapsam ölçümü |

## Dosya yapısı

Testler kaynak dosyanın yanında, `*.test.{js,jsx}` desenli (`vite.config.js` →
`test.include`). Saf mantık `.js`, JSX render gereken `.jsx`.

```
src/
├── hooks/
│   ├── usePrefs.test.js        # saf: sanitize
│   ├── usePrefs.hook.test.js   # durumsal: setPref/toggleDomain/clearAll
│   ├── useConversations.test.js# durumsal: save/list/search/remove/clearAll
│   ├── useAuth.test.js         # saf: decodeJwt/userFromToken
│   ├── useAuth.hook.test.js    # durumsal: guest/logout/token-başlangıç
│   └── useChat.test.js         # durumsal: loadConversation/reset/retryLast
├── lib/
│   ├── parseAnswer.test.js     # SSE→UI köprüsü (mapResponse/mapClarify/...)
│   └── conversationUtils.test.js# arama/kaynak-toplama/dosya-toplama
├── components/
│   ├── ui.test.jsx             # renderInline (markdown) + legalTerms + RunText
│   ├── cards.test.jsx          # AnswerCard (savunmacı) / Reject / Clarify
│   ├── panels.test.jsx         # PredictionCard / AgentTrace / EvidenceStats
│   ├── render.test.jsx         # StreamStepper / Badge / SourceCard / Modal / ConvList
│   ├── accountPanels.test.jsx  # 8 hesap paneli (HowItWorks/Scope/Privacy/...)
│   └── historyPanels.{test.js,render.test.jsx} # relDate + Search/Library/Files
└── pages/
    └── AuthPage.test.jsx       # giriş/kayıt sayfası render
```

**16 dosya · 125 test** (`pnpm test`).

## Kapsam (anlık)

| Alan | Stmts | Lines | Not |
|------|-------|-------|-----|
| `src/hooks` | ~69% | ~73% | Tüm hook durumsal davranışı |
| `src/lib` | ~50% | ~50% | parseAnswer + conversationUtils + legalTerms |
| `src/components` | ~44% | ~54% | Sunum bileşenleri; App.jsx hariç |
| `src/pages` | ~35% | ~45% | AuthPage render |

Düşük kapsamlı kalanlar — `App.jsx`, `UserMenu.jsx` (açık-menü etkileşimi),
`Root.jsx` — büyük **entegrasyon** bileşenleri; birim test yerine gerçek-tarayıcı
E2E ile doğrulanır. Kapsam **gate değil**, bilgilendirici (CI artifact).

## Test yazma desenleri

### 1. Saf fonksiyon
```js
import { describe, it, expect } from "vitest";
import { sanitize } from "./usePrefs.js";
it("bilinmeyen yazı boyutunu normal'e çeker", () => {
  expect(sanitize({ textScale: "huge" }).textScale).toBe("normal");
});
```

### 2. Hook durumsal davranışı (renderHook)
```js
import { renderHook, act } from "@testing-library/react";
const { result } = renderHook(() => usePrefs());
act(() => result.current.setPref("textScale", "large"));
expect(result.current.prefs.textScale).toBe("large");
```
> Not: token yok → backend `fetch` çağrıları sessizce no-op (izole test).

### 3. Bileşen render (statik HTML)
```js
import { renderToStaticMarkup } from "react-dom/server";
const html = (n) => renderToStaticMarkup(n);
expect(html(<RiskWarning text="**süre** önemli" />)).toContain("<strong>süre</strong>");
```
> `renderToStaticMarkup` effect ÇALIŞTIRMAZ → IntersectionObserver/focus-trap
> gibi yan etkiler tetiklenmez; saf render çıktısı doğrulanır.

## CI

`.github/workflows/frontend-ci.yml` — her `frontend/**` push/PR'da:
`pnpm install --frozen-lockfile` → `pnpm test:coverage` → `pnpm build` →
kapsam özetini artifact yükle. Backend CI (`backend-ci.yml`) ayrıdır (~930 test).

## Kural

> Yeni özellik = yeni test (ECC: TDD, %80 hedef). Saf mantığı hook/bileşenden
> ayırıp (`lib/`) doğrudan test et. XSS-kritik render'ı (markdown, legal-term,
> kullanıcı içeriği) mutlaka statik-markup ile doğrula.
