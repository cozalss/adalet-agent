# Frontend

Next.js 15 + React 19 + TypeScript + TailwindCSS web arayüzü.

## Sorumluluklar

- Chat arayüzü (soru + cevap akışı, streaming)
- Ajan kimlik gösterimi (explainability paneli)
- Doğrulama rozetleri (geçerli / risk / belirsiz)
- Güven skoru
- PDF dilekçe indirme
- Belge yükleme (OCR'a giden)
- Hukuki disclaimer her cevapta

## Çalıştır

```bash
npm install
npm run dev
```

`http://localhost:3000` adresinde açılır.

## Stack

- Next.js 15 (App Router)
- React 19, TypeScript
- TailwindCSS + shadcn/ui
- TanStack Query
- Zustand
- React Hook Form + Zod

## Yapılacaklar

- [ ] Next.js projesi başlat (`npx create-next-app@latest .`)
- [ ] Chat sayfası iskeleti
- [ ] Backend API client
- [ ] Dark mode + erişilebilirlik
- [ ] Playwright temel testleri
