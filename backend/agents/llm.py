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


class LLMClient(Protocol):
    """Bütün ajan node'ları bu protokole bağlanır."""

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int = 1024,
        json_mode: bool = False,
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
    ) -> LLMResponse:
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

    def _load(self) -> Any:
        from llama_cpp import Llama

        log.info(
            "llm_loading",
            model_path=self.model_path,
            n_gpu_layers=self.n_gpu_layers,
            n_ctx=self.n_ctx,
        )
        return Llama(
            model_path=self.model_path,
            n_gpu_layers=self.n_gpu_layers,
            n_ctx=self.n_ctx,
            n_batch=512,
            offload_kqv=True,
            verbose=False,
            chat_format=self.chat_format,
        )

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> LLMResponse:
        import asyncio

        if self._model is None:
            self._model = await asyncio.to_thread(self._load)

        kwargs: dict[str, Any] = {
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        result = await asyncio.to_thread(self._model.create_chat_completion, **kwargs)
        choice = result["choices"][0]
        usage = result.get("usage", {})
        return LLMResponse(
            content=choice["message"]["content"],
            raw=result,
            finish_reason=choice.get("finish_reason", "stop"),
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
        )


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
    ) -> LLMResponse:
        import httpx

        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)

        payload: dict[str, Any] = {
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if json_mode:
            # llama.cpp server OpenAI uyumlu — response_format ile JSON grammar
            payload["response_format"] = {"type": "json_object"}

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
        return LLMResponse(
            content=choice["message"]["content"],
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
