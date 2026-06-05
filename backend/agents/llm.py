"""LLM istemcisi — Protocol + iki implementasyon.

Stratejik karar (CLAUDE.md §3): Production'da OpenAI/Anthropic API YOK.
Lokal model şart. Geliştirme ortamı RTX 4070 12GB → Qwen 2.5 14B Q4_K_M GGUF
(llama-cpp-python) yeterli, ~8.5 GB VRAM + ~3 GB KV cache.

Mock client (test/CI için): yapısal yanıtları stub'lar, gerçek inference yok.

Kullanım:
    from agents.llm import get_llm, ChatMessage
    llm = get_llm()
    response = await llm.chat([
        ChatMessage(role="system", content="Sen Türk hukuku asistanısın."),
        ChatMessage(role="user", content="Kıdem tazminatı nedir?"),
    ])
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import structlog

log = structlog.get_logger()

Role = Literal["system", "user", "assistant"]


@dataclass(slots=True)
class ChatMessage:
    role: Role
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(slots=True)
class LLMResponse:
    content: str
    raw: dict[str, Any] | None = None
    finish_reason: str = "stop"
    tokens_in: int = 0
    tokens_out: int = 0


# --- Qwen3 thinking-mode kontrolü -------------------------------------------
# Qwen3 (hibrit) VARSAYILAN olarak <think>...</think> muhakeme bloğu üretir →
# draft parse'ını bozar + UI'a think token'ları akar. `/no_think` yumuşak anahtarı
# bunu kapatır. LLM_NO_THINK=1 ile aktif (Qwen3 GGUF kullanırken run-local-demo set eder;
# Qwen2.5'te /no_think zararsız metin → güvenle açık bırakılabilir).
_NO_THINK = os.getenv("LLM_NO_THINK", "0").lower() in {"1", "true", "yes"}
_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)


_THINK_OPEN_RE = re.compile(r"<think>.*$", re.DOTALL | re.IGNORECASE)


def _strip_think(text: str) -> str:
    """Sızan <think>...</think> bloğunu kes (no-think tutmazsa backstop). Kapanışsız <think>
    (Qwen3.5 ara sıra boş/yarım üretir) → o noktadan sonrası da atılır."""
    cleaned = _THINK_RE.sub("", text or "")
    return _THINK_OPEN_RE.sub("", cleaned).strip()


def _apply_no_think(messages: list[ChatMessage]) -> list[ChatMessage]:
    """LLM_NO_THINK=1 ise system mesajına ` /no_think` ekle (Qwen3 thinking kapatma)."""
    if not _NO_THINK:
        return messages
    out = list(messages)
    for i, m in enumerate(out):
        if m.role == "system":
            out[i] = ChatMessage(role="system", content=f"{m.content} /no_think")
            return out
    return [ChatMessage(role="system", content="/no_think"), *out]


def _hold_partial(s: str, tag: str) -> tuple[str, str]:
    """(safe, tail): tail = s'in, tag'in BAŞLANGICI olabilecek en uzun son-eki → emit edilmez.
    Örn. ('abc<thi', '<think>') → ('abc', '<thi'). Etiket token sınırına bölünürse korunur.
    Büyük/küçük harf duyarsız (tag lowercase; <THINK> de tutulur)."""
    low = s.lower()
    for k in range(min(len(s), len(tag) - 1), 0, -1):
        if low.endswith(tag[:k]):
            return s[:-k], s[-k:]
    return s, ""


class _StreamThinkFilter:
    """Akan token'larda <think>...</think> bloğunu (Qwen3.5 boş üretse bile) UI'a SIZDIRMADAN kes.

    Token'lar parça parça + etiket token sınırına bölünebilir → tampon + kısmi-etiket koruması.
    on_token yerine bu filtreden geçen 'temiz' delta emit edilir; <think> içeriği + etiketler
    düşürülür. (Dönen TAM içerik ayrıca _strip_think ile temizlenir — bu yalnız akış UI içindir.)
    """

    _OPEN = "<think>"
    _CLOSE = "</think>"

    def __init__(self, emit: Callable[[str], None]) -> None:
        self._emit = emit
        self._buf = ""
        self._in_think = False

    def feed(self, delta: str) -> None:
        self._buf += delta
        send: list[str] = []
        while self._buf:
            low = self._buf.lower()  # case-insensitive arama (<THINK>/<Think> de yakalanır)
            if not self._in_think:
                i = low.find(self._OPEN)
                if i == -1:
                    safe, tail = _hold_partial(self._buf, self._OPEN)
                    if safe:
                        send.append(safe)
                    self._buf = tail
                    break
                if i:
                    send.append(self._buf[:i])
                self._buf = self._buf[i + len(self._OPEN):]
                self._in_think = True
            else:
                j = low.find(self._CLOSE)
                if j == -1:
                    _, self._buf = _hold_partial(self._buf, self._CLOSE)  # think içeriği AT
                    break
                self._buf = self._buf[j + len(self._CLOSE):]
                self._in_think = False
        if send:
            self._emit("".join(send))

    def flush(self) -> None:
        if not self._in_think and self._buf:
            self._emit(self._buf)
        self._buf = ""


class LLMClient(Protocol):
    """Bütün ajan node'ları bu protokole bağlanır."""

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int = 1024,
        json_mode: bool = False,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse: ...


class MockLLM:
    """Test/CI client — gerçek model yok, deterministik dummy yanıt.

    JSON mode'da geçerli {"label": "...", "confidence": ...} döner ki
    LangGraph akışı çalıştığı test edilebilsin.
    """

    def __init__(self, fixed_response: str | None = None) -> None:
        self.fixed_response = fixed_response
        self.call_count = 0

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int = 1024,
        json_mode: bool = False,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        # MockLLM json_schema'yı yok sayar (gerçek grammar yok); json_mode davranışı korunur.
        self.call_count += 1
        if self.fixed_response is not None:
            content = self.fixed_response
        elif json_mode:
            content = _mock_json_response(messages)
        else:
            content = (
                "[MOCK] Test cevabı — gerçek LLM bağlanmadı. "
                "Bu mock yanıt LangGraph akışını doğrulamak içindir. "
                "Kaynaklara dayalı gerçek hukuki sentez yalnız llamacpp modunda yapılır."
            )
        return LLMResponse(content=content)


class LlamaCppClient:
    """llama-cpp-python — Qwen 2.5 14B-Instruct Q4_K_M GGUF.

    Lazy-load: ilk chat() çağrısında model GPU'ya yüklenir (~3 sn).
    Singleton kullan (get_llm), tekrar tekrar yükleme yapma.
    """

    def __init__(
        self,
        model_path: str,
        n_gpu_layers: int = -1,        # -1 = hepsi GPU'ya
        n_ctx: int = 8192,
        chat_format: str = "chatml",   # Qwen 2.5 chatml kullanır
    ) -> None:
        self.model_path = model_path
        self.n_gpu_layers = n_gpu_layers
        self.n_ctx = n_ctx
        self.chat_format = chat_format
        self._model: Any = None
        # Lazy asyncio.Lock — eşzamanlı ilk istekler modeli İKİ KEZ yüklemesin
        # (çift GPU bellek → OOM). Lazy: __init__'te running loop gerekmez.
        self._load_lock: Any = None
        # Tek-worker decode executor: çağıran asyncio.wait_for ile timeout atsa
        # bile decode thread'i GPU'da çalışmaya devam eder. Aynı self._model
        # üzerinde paralel create_chat_completion → KV-cache yarışı → llama_decode
        # -1 (kira e2e'de görüldü: multi-query timeout sonrası eligibility çöktü).
        # Single-worker executor yeni işi kuyruğa alır, asla yarışmaz.
        self._decode_executor: Any = None

    def _load(self) -> Any:
        # Windows: llama.dll'in CUDA bağımlılıkları (cudart64_12, cublas64_12)
        # torch'un (cu124) bundle ettiği DLL'lerde mevcut. torch/lib'i DLL arama
        # yoluna ekle → CUDA Toolkit kurmadan GPU offload. Toolkit yoksa "llama.dll
        # bağımlılığı bulunamadı" ile yükleme çökerdi. Guard'lı: torch yoksa/Linux'ta
        # no-op (binary'ler kendi runtime'ını bundle eder).
        import contextlib
        with contextlib.suppress(Exception):
            import os as _os

            import torch as _torch
            _lib = _os.path.join(_os.path.dirname(_torch.__file__), "lib")
            if hasattr(_os, "add_dll_directory") and _os.path.isdir(_lib):
                _os.add_dll_directory(_lib)

        import os as _os2

        from llama_cpp import Llama

        # KAYIPSIZ hızlandırma (çıktı dağılımı DEĞİŞMEZ — kalite aynı, decode hızlı):
        #  - prompt-lookup speculative decoding: taslak token'ları prompt'tan n-gram
        #    lookup ile önerir, model doğrular. RAG'de cevap getirilen kanun/karar
        #    metnini tekrar ettiğinden isabet yüksek → ~1.5-2× decode. (lossless)
        #  - flash_attn: flash-attention kernel (bellek + hız).
        # LLM_SPECULATIVE=0 / LLM_FLASH_ATTN=0 ile kapatılır (sorun çıkarsa).
        draft_model = None
        if _os2.getenv("LLM_SPECULATIVE", "1").lower() in {"1", "true", "yes"}:
            with contextlib.suppress(Exception):
                from llama_cpp.llama_speculative import LlamaPromptLookupDecoding
                draft_model = LlamaPromptLookupDecoding(num_pred_tokens=10)
        flash_attn = _os2.getenv("LLM_FLASH_ATTN", "1").lower() in {"1", "true", "yes"}

        # n_threads opsiyonel (LLM_N_THREADS); varsayılan = llama.cpp kendi seçer
        # (fiziksel çekirdek). Düşük değer uzun-prompt prefill'ini YAVAŞLATIR
        # (CPU-side batch ops), o yüzden default'a dokunmuyoruz.
        _nt = _os2.getenv("LLM_N_THREADS")
        n_threads = int(_nt) if _nt else None

        log.info(
            "llm_loading",
            model_path=self.model_path,
            n_gpu_layers=self.n_gpu_layers,
            n_ctx=self.n_ctx,
            flash_attn=flash_attn,
            speculative=draft_model is not None,
            n_threads=n_threads,
        )
        kwargs: dict[str, Any] = {
            "model_path": self.model_path,
            "n_gpu_layers": self.n_gpu_layers,
            "n_ctx": self.n_ctx,
            # prompt-processing throughput; flash_attn KV-cache'i küçülttüğünden
            # 4070'te 1024 sığar. VRAM dararsa LLM_N_BATCH=512.
            "n_batch": int(_os2.getenv("LLM_N_BATCH", "1024")),
            "offload_kqv": True,
            "flash_attn": flash_attn,
            "draft_model": draft_model,
            "verbose": False,
            "chat_format": self.chat_format,
        }
        if n_threads is not None:
            kwargs["n_threads"] = n_threads
            kwargs["n_threads_batch"] = n_threads
        return Llama(**kwargs)

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int = 1024,
        json_mode: bool = False,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        import asyncio

        if self._model is None:
            # Double-checked lock: lock oluşturma tek event-loop'ta atomik
            # (check↔assign arası await yok). İlk yükleme lock altında serialize
            # → eşzamanlı istekler tek load; sonraki çağrılarda lock alınmaz.
            if self._load_lock is None:
                self._load_lock = asyncio.Lock()
            async with self._load_lock:
                if self._model is None:
                    self._model = await asyncio.to_thread(self._load)

        messages = _apply_no_think(messages)  # Qwen3 thinking kapat (LLM_NO_THINK=1)
        # Context-taşma guard: prompt + cevap n_ctx'i aşarsa llama_decode -1 ile
        # ÇÖKER (kira/tapu gibi uzun-maddeli domain'lerde görüldü). max_tokens'ı
        # prompt'a göre clamp et — cevap kısalır ama sistem çökmez.
        max_tokens = self._fit_max_tokens(messages, max_tokens)

        kwargs: dict[str, Any] = {
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_schema is not None:
            # Guided decoding (2.2): JSON-schema → GBNF (llama-cpp-python otomatik çevirir).
            # cite_id enum'u decode-seviyesinde kısıtlanır → uydurma cite ÜRETİLEMEZ
            # (post-hoc filtreden önce, claim-cite kopukluğu olmadan). json_object'ün üstünde.
            kwargs["response_format"] = {"type": "json_object", "schema": json_schema}
        elif json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        # Tek-worker decode executor — asyncio.to_thread global pool'u kullansa
        # eşzamanlı chat() çağrıları aynı self._model'i yarıştırırdı. Ayrı 1-worker
        # executor: wait_for cancel olsa da thread çalışmaya devam eder, yeni iş
        # kuyrukta bekler, decode'lar SIRAYLA koşar. Yarış yok → llama_decode -1 yok.
        if self._decode_executor is None:
            import concurrent.futures
            self._decode_executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="llama-decode",
            )
        cf_future = self._decode_executor.submit(
            self._model.create_chat_completion, **kwargs,
        )
        result = await asyncio.wrap_future(cf_future)
        choice = result["choices"][0]
        usage = result.get("usage", {})
        return LLMResponse(
            content=_strip_think(choice["message"]["content"]),
            raw=result,
            finish_reason=choice.get("finish_reason", "stop"),
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
        )

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int = 1024,
        on_token: Callable[[str], None],
    ) -> LLMResponse:
        """chat() ile aynı üretim, AMA token'lar üretildikçe on_token(delta) ile yayılır.

        on_token EVENT-LOOP thread'inde çağrılır (call_soon_threadsafe) → çağıran
        güvenle async kuyruğa put_nowait edebilir. Tam içerik LLMResponse.content'te
        döner (çağıran doğrulamaya yine TAM metni verir; akış yalnız UI içindir).
        """
        import asyncio

        if self._model is None:
            if self._load_lock is None:
                self._load_lock = asyncio.Lock()
            async with self._load_lock:
                if self._model is None:
                    self._model = await asyncio.to_thread(self._load)

        messages = _apply_no_think(messages)  # Qwen3 thinking kapat (stream'e think token akmasın)
        max_tokens = self._fit_max_tokens(messages, max_tokens)
        kwargs: dict[str, Any] = {
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        loop = asyncio.get_running_loop()

        def _emit_token(s: str) -> None:
            loop.call_soon_threadsafe(on_token, s)

        def _run_stream() -> str:
            parts: list[str] = []
            # <think> akış-filtresi: Qwen3.5 boş <think></think> üretse bile UI'a sızdırma.
            think_filter = _StreamThinkFilter(_emit_token)
            for chunk in self._model.create_chat_completion(**kwargs):
                try:
                    delta = chunk["choices"][0]["delta"].get("content")
                except (KeyError, IndexError, TypeError):
                    delta = None
                if delta:
                    parts.append(delta)  # TAM içerik (return için; ayrıca _strip_think'lenir)
                    think_filter.feed(delta)  # UI'a yalnız <think>-dışı temiz delta
            think_filter.flush()
            return "".join(parts)

        # chat() ile aynı tek-worker decode executor (KV-cache yarışını önler).
        if self._decode_executor is None:
            import concurrent.futures
            self._decode_executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="llama-decode",
            )
        cf_future = self._decode_executor.submit(_run_stream)
        content = await asyncio.wrap_future(cf_future)
        return LLMResponse(content=_strip_think(content), raw={}, finish_reason="stop")

    # En az bu kadar token cevaba bırakılır (clamp tabanı); chat template + güvenlik payı.
    _MIN_OUTPUT_TOKENS = 256
    _CTX_MARGIN_TOKENS = 64

    def _fit_max_tokens(self, messages: list[ChatMessage], requested: int) -> int:
        """prompt + max_tokens ≤ n_ctx olacak şekilde max_tokens'ı clamp et.

        Modelin kendi tokenizer'ıyla prompt token'ları sayılır (chat template
        overhead'i mesaj başına ~8 token eklenir). prompt zaten n_ctx'e yakınsa
        cevap tabana (256) iner; bu durumda prompt çağıran node tarafından
        kısaltılmalı (draft ref bütçesi) — guard yine de hard-crash'i önler.
        """
        try:
            prompt_tokens = sum(
                len(self._model.tokenize(
                    m.content.encode("utf-8"), add_bos=False, special=False,
                ))
                for m in messages
            ) + 8 * (len(messages) + 1)
        except Exception:
            # Tokenizer erişilemezse muhafazakar tahmin (Türkçe ~2.3 char/token).
            prompt_tokens = int(sum(len(m.content) for m in messages) / 2.3) + 16

        available = self.n_ctx - prompt_tokens - self._CTX_MARGIN_TOKENS
        if available < requested:
            clamped = max(available, self._MIN_OUTPUT_TOKENS)
            log.warning(
                "llm_ctx_clamp",
                requested=requested, clamped=clamped,
                prompt_tokens=prompt_tokens, n_ctx=self.n_ctx,
            )
            return clamped
        return requested


class LlamaCppServerClient:
    """llama.cpp standalone server üzerinden OpenAI-uyumlu HTTP istemci.

    Neden bu, llama-cpp-python yerine?
      - llama-cpp-python CUDA wheel'ı sistem CUDA Toolkit DLL'leri ister
        (cudart64_*.dll, cublas64_*.dll). Sadece driver yetmez, Toolkit
        kurulu olmayabilir.
      - llama.cpp standalone binary CUDA DLL'lerini BUNDLE eder — sıfır
        ek kurulum, RTX 4070 + driver yeter.
      - Tek model load, çoklu Python process (FastAPI worker'lar) tek
        modeli paylaşır.

    Başlatma (manuel, ayrı terminal — production'da systemd/Docker):
        llama-server.exe --model qwen.gguf --port 8080 -ngl 99 --ctx-size 8192

    Singleton kullanım:
        export LLM_MODE=llamacpp_server
        export LLM_SERVER_URL=http://127.0.0.1:8080  (default)
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        timeout: float = 120.0,
        model_name: str = "qwen",  # llama-server slot adı; gerçek model server'da seçili
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.model_name = model_name
        self._client: Any = None

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int = 1024,
        json_mode: bool = False,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        import httpx

        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)

        messages = _apply_no_think(messages)  # Qwen3 thinking kapat (LLM_NO_THINK=1)
        payload: dict[str, Any] = {
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if json_schema is not None:
            # Guided decoding (2.2): OpenAI uyumlu json_schema → llama.cpp GBNF grammar.
            # cite_id enum'u decode-seviyesinde kısıtlanır (uydurma cite üretilemez).
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "claims", "schema": json_schema, "strict": True},
            }
        elif json_mode:
            # llama.cpp server OpenAI uyumlu — response_format ile JSON grammar
            payload["response_format"] = {"type": "json_object"}

        started = time.perf_counter()
        try:
            resp = await self._client.post(
                f"{self.base_url}/v1/chat/completions", json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.warning("llama_server_call_failed", error=str(exc), url=self.base_url)
            raise

        choice = data["choices"][0]
        usage = data.get("usage", {})
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        log.info(
            "llama_server_call_done",
            elapsed_ms=elapsed_ms,
            json_mode=json_mode,
            max_tokens=max_tokens,
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
        )
        return LLMResponse(
            content=_strip_think(choice["message"]["content"]),
            raw=data,
            finish_reason=choice.get("finish_reason", "stop"),
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


_singleton: LLMClient | None = None


def get_llm() -> LLMClient:
    """Process-singleton LLM. ENV ile seçilebilir.

    LLM_MODE=mock              → MockLLM (test, CI, hızlı dev)
    LLM_MODE=llamacpp          → LlamaCppClient (in-proc Python, CUDA Toolkit gerek)
    LLM_MODE=llamacpp_server   → LlamaCppServerClient (HTTP, prebuilt binary, RTX 4070)
    LLM_MODEL_PATH=...         → GGUF dosya yolu (llamacpp için zorunlu)
    LLM_SERVER_URL=...         → llama-server endpoint (default 127.0.0.1:8080)
    """
    global _singleton
    if _singleton is not None:
        return _singleton

    mode = os.environ.get("LLM_MODE", "mock").lower()
    if mode == "llamacpp":
        path = os.environ.get("LLM_MODEL_PATH")
        if not path or not os.path.exists(path):
            raise RuntimeError(
                f"LLM_MODE=llamacpp seçildi ama LLM_MODEL_PATH yok veya bulunamadı: {path}"
            )
        _singleton = LlamaCppClient(model_path=path)
    elif mode in {"llamacpp_server", "llama_server", "server"}:
        url = os.environ.get("LLM_SERVER_URL", "http://127.0.0.1:8080")
        _singleton = LlamaCppServerClient(base_url=url)
        log.info("llm_using_llamacpp_server", url=url)
    else:
        _singleton = MockLLM()
        log.warning("llm_using_mock", note="LLM_MODE=llamacpp seçmek için ortamı ayarla")
    return _singleton


def reset_llm() -> None:
    """Test fixture — singleton'u sıfırla."""
    global _singleton
    _singleton = None


# MockLLM için kaba domain keyword routing — sadece smoke test akışı için
_MOCK_DOMAIN_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("isHukuku",   ("kıdem", "ihbar", "işçi", "mobbing", "fazla mesai")),
    ("kira", ("kira", "depozito", "tahliye", "ev sahibi", "kiracı")),
    ("tuketici",   ("tüketici", "ayıplı", "garanti", "iade", "satın al")),
    ("icra",       ("icra", "haciz", "borç", "takip")),
    ("trafik",     ("trafik", "kaza", "sigorta", "ehliyet", "plaka")),
    ("vergi",      ("vergi", "kdv", "ötv")),
    ("tapu",       ("tapu", "mülkiyet", "kat mülkiyeti")),
    ("idari",      ("kamulaştırma", "vatandaşlık", "idari")),
]


def _mock_domain_from_messages(messages: list[ChatMessage]) -> str:
    """Son user mesajından kaba keyword tabanlı domain — sadece MockLLM için."""
    user_text = " ".join(m.content for m in messages if m.role == "user").lower()
    for domain, kws in _MOCK_DOMAIN_KEYWORDS:
        if any(kw in user_text for kw in kws):
            return domain
    return "unknown"


# Mock JSON şablonları — _mock_json_response dispatch table.
# system_text'in tetikleyicisi → JSON payload. İlk eşleşen kazanır.
_MOCK_PARAPHRASE_BASE = "soru"  # _multi_query_paraphrases içinde override edilir


def _mock_multi_query_paraphrases(messages: list[ChatMessage]) -> str:
    user_text = " ".join(m.content for m in messages if m.role == "user")
    base = user_text.strip()[:120] or _MOCK_PARAPHRASE_BASE
    return json.dumps(
        {"paraphrases": [f"[MOCK paraphrase {i}] {base}" for i in range(1, 5)]},
        ensure_ascii=False,
    )


# (predicate(system_text) -> bool, payload_builder(messages, system_text) -> str)
# Sıra önemli: önce spesifik, sonra genel ("hakem"/"verdict" en sonda kalsın).
_MOCK_DISPATCH: tuple[tuple[Any, Any], ...] = (
    (lambda s: "paraphrases" in s,
     lambda msgs, _s: _mock_multi_query_paraphrases(msgs)),
    (lambda s: "faithful" in s and "complete" in s,
     lambda _m, _s: json.dumps(
         {"faithful": 0.85, "complete": 0.75, "tone": 0.80,
          "notes": "[MOCK] Judge: ölçütler test seviyesinde."},
         ensure_ascii=False)),
    (lambda s: "self-rag" in s or ("retrieve" in s and "supported" in s and "utility" in s),
     lambda _m, _s: json.dumps(
         {"retrieve": "no", "supported": "yes", "utility": 5,
          "notes": "[MOCK] Self-RAG: yansıma testi, tüm reflection tokens pozitif."},
         ensure_ascii=False)),
    (lambda s: "claim" in s and ("çıkart" in s or "atomic" in s),
     lambda _m, _s: json.dumps(
         {"claims": ["[MOCK] Atomic claim 1.", "[MOCK] Atomic claim 2."]},
         ensure_ascii=False)),
    (lambda s: "uygunluk değerlendir" in s,
     lambda _m, _s: json.dumps(
         {"degerlendirmeler": [
             {"madde": "m-MOCK-1", "hak": "[MOCK] hak", "kosul": "-",
              "saglaniyor": "belirsiz", "gerekce": "[MOCK] uygunluk testi."},
         ]},
         ensure_ascii=False)),
    (lambda s: "entailment" in s,
     lambda _m, _s: json.dumps(
         {"verdict": "yes", "reason": "[MOCK] context destekliyor."},
         ensure_ascii=False)),
    (lambda s: "soru üretici" in s or ("questions" in s and "soru" in s),
     lambda _m, _s: json.dumps(
         {"questions": ["[MOCK] Test sorusu 1?", "[MOCK] Test sorusu 2?"]},
         ensure_ascii=False)),
    (lambda s: "kaynak hakem" in s or "useful" in s,
     lambda _m, _s: json.dumps(
         {"useful": "yes", "reason": "[MOCK] kaynak gerekli."},
         ensure_ascii=False)),
    (lambda s: "hakem" in s or "verdict" in s or "constitutional" in s,
     lambda _m, _s: json.dumps(
         {"verdict": "pass", "score": 0.78, "issues": [],
          "revised_answer": None,
          "rationale": "[MOCK] Debate hakem: taslak kaynaklarla tutarlı görünüyor."},
         ensure_ascii=False)),
)


def _mock_json_response(messages: list[ChatMessage]) -> str:
    """MockLLM json_mode router — system prompt'tan hangi node çağırdığını anla.

    Dispatch table pattern: _MOCK_DISPATCH (predicate, builder) tuple'larını
    sırayla dener. İlk eşleşmenin payload'u döner. Hiçbiri eşleşmezse default
    triaj cevabı üretir.
    """
    system_text = " ".join(m.content for m in messages if m.role == "system").lower()

    for predicate, builder in _MOCK_DISPATCH:
        if predicate(system_text):
            return str(builder(messages, system_text))

    # Default: triaj
    domain = _mock_domain_from_messages(messages)
    return json.dumps(
        {"domain": domain, "confidence": 0.85, "reasoning": "MockLLM tahmini"},
        ensure_ascii=False,
    )
