"""LLM istemcisi — Protocol + dört implementasyon (mock / openai / llamacpp / llamacpp_server).

Strateji (CLAUDE.md v2.3): "en iyi teknoloji serbest" — bulut API'ler (OpenAI gpt-4o/mini)
ana LLM olabilir; lokal model (Qwen GGUF, llama-cpp-python) hâlâ desteklenir (artık kısıt
değil, tercih). LLM_MODE ile seçilir; anahtarlar .env'de (asla hardcode). get_llm() dispatch eder.
Lokal Qwen geliştirme ortamı: RTX 4070 12GB → Qwen3.5-9B Q4_K_XL GGUF (~6 GB VRAM).

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

import concurrent.futures
import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import structlog

from core.openai_compat import _retry_delay, require_api_key, validated_base_url

log = structlog.get_logger()

Role = Literal["system", "user", "assistant"]

# llama.cpp KV-cache quantization tipleri (modül sabiti — N806; _load() içinde tekrar
# tanımlanıyordu). f16=1 (default/kayıpsız), q8_0=8 (~yarı VRAM), q4_0=2.
_KV_TYPES = {"f16": 1, "q8_0": 8, "q4_0": 2}

# OpenAI SSE akışı bellek tavanı: kötü/SSRF proxy sonsuz akışla worker'ı OOM etmesin.
# Meşru hukuki cevaplar << 200K karakter (max_tokens zaten sınırlar; bu ek savunma).
_STREAM_MAX_CHARS = int(os.getenv("OPENAI_STREAM_MAX_CHARS", str(200_000)))


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
        # __init__'te yarat (lazy DEĞİL): iki eşzamanlı ilk-çağrı `is None` görüp İKİ
        # ayrı executor kurarsa serileştirme garantisi kırılırdı (race). ThreadPoolExecutor
        # thread'i ilk submit'e kadar spawn etmez → eager yaratma bedava.
        self._decode_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="llama-decode",
        )

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

        # KV-cache quantization (opt-in). q8_0 ~kayıpsız (perplexity +<0.1) ve KV-cache'i
        # ~yarıya indirir → VRAM açar (4070 12GB'da Qwen+yardımcılarla sıkışıkken kritik) ve
        # decode'u biraz hızlandırır. flash_attn ŞART (yoksa her adımda dequantize → yavaş).
        # Default f16 (mevcut davranış — sıfır değişiklik); LLM_KV_TYPE=q8_0 ile aç. Bozarsa f16.
        _kv = _os2.getenv("LLM_KV_TYPE", "f16").lower()
        kv_type = _KV_TYPES.get(_kv, 1)
        kv_quant = kv_type != 1 and flash_attn

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
        if kv_quant:  # yalnız opt-in + flash_attn açıkken (yoksa atla → güvenli)
            kwargs["type_k"] = kv_type
            kwargs["type_v"] = kv_type
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

        # Tek-worker decode executor (__init__'te kuruldu) — asyncio.to_thread global
        # pool'u kullansa eşzamanlı chat() çağrıları aynı self._model'i yarıştırırdı.
        # Ayrı 1-worker executor: wait_for cancel olsa da thread çalışmaya devam eder,
        # yeni iş kuyrukta bekler, decode'lar SIRAYLA koşar. Yarış yok → llama_decode -1 yok.
        cf_future = self._decode_executor.submit(
            self._model.create_chat_completion, **kwargs,
        )
        result = await asyncio.wrap_future(cf_future)
        choices = result.get("choices") or []
        if not choices:
            raise ValueError("LlamaCpp yanıtında choices boş")
        choice = choices[0]
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

        # chat() ile aynı tek-worker decode executor (__init__'te kuruldu; KV-cache yarışını önler).
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

    async def aclose(self) -> None:
        """Decode executor'ı kapat (lifespan shutdown — aclose_llm getattr ile çağırır).
        Aksi halde SIGTERM'de tek-worker thread orphan kalır; hızlı restart'ta birikir."""
        self._decode_executor.shutdown(wait=False)


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

        choices = data.get("choices") or []
        if not choices:
            raise ValueError("llama-server yanıtında choices boş")
        choice = choices[0]
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


class OpenAIClient:
    """OpenAI (gpt-4o / gpt-4o-mini) Chat Completions — bulut ana LLM (v2.3).

    Tüm ajan node'ları get_llm()'den geçtiği için TEK bu client ile draft/finalize/dilekçe/
    HyDE/sorgu-yeniden-yazma/clarifier hepsi gpt-4o kullanır. Raw httpx (openai SDK yok,
    stt_cloud deseni). json_schema → json_object (GBNF yok; cite doğruluğu post-hoc filtrede).
    _apply_no_think UYGULANMAZ (Qwen'e özgü). Anahtar .env'de (asla hardcode).
    """

    def __init__(
        self,
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        model_name = model if model is not None else os.getenv("OPENAI_LLM_MODEL")
        self.model = (model_name or "gpt-4o-mini").strip() or "gpt-4o-mini"
        self.base_url = validated_base_url()
        self.timeout = timeout if timeout is not None else float(os.getenv("OPENAI_LLM_TIMEOUT_S", "120"))
        self._client: Any = None  # httpx.AsyncClient — process ömrü boyu yeniden kullanılır

    def _ensure_client(self) -> Any:
        import httpx

        if self._client is None:
            # follow_redirects=False: SSRF redirect-bypass sertleştirme (yargi_client deseni).
            self._client = httpx.AsyncClient(timeout=self.timeout, follow_redirects=False)
        return self._client

    def _headers(self) -> dict[str, str]:
        # Anahtarı call-time oku (require_api_key) → singleton sonrası set edilse de güncel.
        key = require_api_key("LLM_MODE=openai")
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def _payload(
        self, messages: list[ChatMessage], temperature: float, max_tokens: int,
        *, json_mode: bool, json_schema: dict[str, Any] | None, stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "stream": stream,
        }
        # Yeni-nesil muhakeme modelleri (o1/o3/o4/gpt-5): 'max_tokens' YERİNE 'max_completion_tokens'
        # ve 'temperature' yalnız default(1) destekler → özel temp GÖNDERME (400 hatası önlenir).
        # gpt-4o ailesi (default): klasik parametreler. İleride model değişse de kod kırılmaz.
        if re.match(r"^(o[1-9]|gpt-5)", self.model):
            payload["max_completion_tokens"] = max_tokens
        else:
            payload["temperature"] = temperature
            payload["max_tokens"] = max_tokens
        # json_schema da dahil → json_object (OpenAI strict-schema formatı kırılgan; geçerli
        # JSON garantisi + prompt yönlendirmesi + post-hoc filtre yeterli).
        if json_mode or json_schema is not None:
            payload["response_format"] = {"type": "json_object"}
        if stream:
            payload["stream_options"] = {"include_usage": True}
        return payload

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

        import httpx

        client = self._ensure_client()
        payload = self._payload(
            messages, temperature, max_tokens,
            json_mode=json_mode, json_schema=json_schema, stream=False,
        )
        url = f"{self.base_url}/chat/completions"
        started = time.perf_counter()
        # Geçici hatalarda (429/5xx/ağ) kısa retry — kalıcı (4xx auth) hemen yükselir.
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = await client.post(url, json=payload, headers=self._headers())
                resp.raise_for_status()
                data = resp.json()
                break
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                code = exc.response.status_code
                if code in (429, 500, 502, 503, 504) and attempt < 2:
                    await asyncio.sleep(_retry_delay(1.0, attempt, exc.response))
                    continue
                log.warning("openai_llm_failed", status=code)
                raise
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                    continue
                log.warning("openai_llm_failed", error=type(exc).__name__)
                raise
        else:  # pragma: no cover — döngü break/raise ile çıkar
            raise last_exc or RuntimeError("openai_llm_unreachable")

        choices = data.get("choices") or []
        if not choices:
            raise ValueError(f"OpenAI yanıtında choices boş: {str(data)[:200]}")
        choice = choices[0]
        usage = data.get("usage", {})
        log.info(
            "openai_llm_done", model=self.model,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            tokens_in=usage.get("prompt_tokens", 0), tokens_out=usage.get("completion_tokens", 0),
        )
        return LLMResponse(
            content=_strip_think(choice["message"]["content"] or ""),
            raw=data,
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
        """OpenAI SSE streaming — token'lar üretildikçe on_token(delta). Async (event loop'ta)
        çağrıldığı için on_token doğrudan çağrılır (threadsafe sarmaya gerek yok).

        Retry YALNIZ bağlantı seviyesinde (token emit edilmeden, 429/5xx); token akmaya
        başlayınca ortada retry edilmez (çift-token olur) → propagate. Bellek: birikim
        _STREAM_MAX_CHARS ile sınırlı (kötü/SSRF proxy sonsuz akış → OOM önle)."""
        import asyncio

        import httpx

        client = self._ensure_client()
        payload = self._payload(
            messages, temperature, max_tokens, json_mode=False, json_schema=None, stream=True,
        )
        url = f"{self.base_url}/chat/completions"
        parts: list[str] = []
        total_chars = 0
        tokens_in = 0
        tokens_out = 0
        last_exc: Exception | None = None
        for attempt in range(3):
            parts.clear()  # retry'a yalnız token emit edilmeden gelinir → temiz başla
            total_chars = 0
            try:
                async with client.stream(
                    "POST", url, json=payload, headers=self._headers(),
                ) as resp:
                    try:
                        resp.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        code = exc.response.status_code
                        if code in (429, 500, 502, 503, 504) and attempt < 2:
                            last_exc = exc
                            await asyncio.sleep(_retry_delay(1.0, attempt, exc.response))
                            continue  # token emit edilmedi → güvenli retry
                        log.warning("openai_stream_failed", status=code)
                        raise
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        chunk_str = line[5:].strip()
                        if not chunk_str or chunk_str == "[DONE]":
                            continue
                        try:
                            chunk = json.loads(chunk_str)
                        except json.JSONDecodeError:
                            continue
                        choices = chunk.get("choices") or []
                        if not choices:  # son usage-only chunk (include_usage)
                            usage = chunk.get("usage") or {}
                            tokens_in = usage.get("prompt_tokens", tokens_in)
                            tokens_out = usage.get("completion_tokens", tokens_out)
                            continue
                        delta = (choices[0].get("delta") or {}).get("content")
                        if delta:
                            total_chars += len(delta)
                            if total_chars > _STREAM_MAX_CHARS:
                                raise RuntimeError("SSE akışı boyut sınırını aştı")
                            parts.append(delta)
                            on_token(delta)
                return LLMResponse(
                    content=_strip_think("".join(parts)), raw={}, finish_reason="stop",
                    tokens_in=tokens_in, tokens_out=tokens_out,
                )
            except httpx.HTTPError as exc:
                # transport hata: token AKMADIYSA (parts boş) retry güvenli; aktıysa propagate.
                if not parts and attempt < 2:
                    last_exc = exc
                    await asyncio.sleep(2 ** attempt)
                    continue
                log.warning("openai_stream_failed", error=type(exc).__name__)
                raise
        raise last_exc or RuntimeError("openai_stream_unreachable")  # pragma: no cover

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


_singleton: LLMClient | None = None


def get_llm() -> LLMClient:
    """Process-singleton LLM. ENV ile seçilebilir.

    LLM_MODE=mock              → MockLLM (test, CI, hızlı dev)
    LLM_MODE=openai            → OpenAIClient (bulut gpt-4o/gpt-4o-mini — en iyi kalite, v2.3)
    LLM_MODE=llamacpp          → LlamaCppClient (in-proc Python, CUDA Toolkit gerek)
    LLM_MODE=llamacpp_server   → LlamaCppServerClient (HTTP, prebuilt binary, RTX 4070)
    LLM_MODEL_PATH=...         → GGUF dosya yolu (llamacpp için zorunlu)
    LLM_SERVER_URL=...         → llama-server endpoint (default 127.0.0.1:8080)
    OPENAI_LLM_MODEL=...       → openai modeli (default gpt-4o-mini; gpt-4o = max kalite)
    """
    global _singleton
    if _singleton is not None:
        return _singleton

    mode = os.environ.get("LLM_MODE", "mock").lower()
    if mode == "openai":
        if not os.environ.get("OPENAI_API_KEY", "").strip():
            log.warning("openai_llm_no_key_fallback_mock",
                        note="LLM_MODE=openai ama OPENAI_API_KEY yok → mock'a düşüldü")
            _singleton = MockLLM()
        else:
            _singleton = OpenAIClient()
            log.info("llm_using_openai", model=os.getenv("OPENAI_LLM_MODEL", "gpt-4o-mini"))
    elif mode == "llamacpp":
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


# Tiered routing (LLM_TIER_ROUTING): karmaşık/yüksek-riskli sorular için güçlü model (gpt-4o).
# openai modunda model BAŞINA ayrı OpenAIClient cache'lenir (bağlantı havuzu paylaşımı). Default
# model ya da openai-dışı mod → base singleton (ekstra client AÇILMAZ → sıfır ek kaynak).
_tier_clients: dict[str, LLMClient] = {}


def get_llm_for_model(model: str | None) -> LLMClient:
    """Belirli bir OpenAI modeli için client döndür (tiered routing — draft tarafı seçer).

    model None/boş → base singleton. openai-dışı mod (lokal/mock tek model) → base singleton.
    model == base model → base singleton (ekstra bağlantı havuzu açma). Aksi → model'e özel
    OpenAIClient (process boyu cache'li). aclose_llm hepsini kapatır.
    """
    base = get_llm()
    # Mod kararını base singleton'ın TİPİNE bağla (env'i yeniden okumak yerine) → get_llm ile
    # aynı karar yolu (LLM_MODE singleton kurulduktan sonra değişse bile tutarlı; ECC review MEDIUM).
    if not model or not isinstance(base, OpenAIClient):
        return base
    model = model.strip()
    if not model or model == getattr(base, "model", None):
        return base
    client = _tier_clients.get(model)
    if client is None:
        client = OpenAIClient(model=model)
        _tier_clients[model] = client
        log.info("llm_tier_client_created", model=model)
    return client


def reset_llm() -> None:
    """Test fixture — singleton'u + tier cache'i sıfırla."""
    global _singleton
    _singleton = None
    _tier_clients.clear()


async def aclose_llm() -> None:
    """LLM singleton'unu + tier client'larını temiz kapat (varsa). Lifespan shutdown'da çağrılır —
    openai/llamacpp_server modundaki httpx bağlantılarını kapatır (Qdrant/DB teardown deseniyle
    tutarlı). aclose'u olmayan (MockLLM) no-op."""
    targets = ([_singleton] if _singleton is not None else []) + list(_tier_clients.values())
    for client in targets:
        aclose = getattr(client, "aclose", None)
        if aclose is not None:
            await aclose()


# MockLLM + mock dispatch → agents/llm_mock.py (CLAUDE.md <800). DİP re-export, circular-safe:
# llm_mock llm.py'nin SONUNDA import edilir → ChatMessage/LLMResponse tanımlı.
from agents.llm_mock import MockLLM  # noqa: E402
