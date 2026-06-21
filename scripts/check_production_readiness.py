"""Repository-level production readiness gate.

This is an offline/static gate: it proves that the repo carries the production
contracts needed before a live deploy smoke can be meaningful. It intentionally
does not require Docker, GPU, Supabase credentials, Qdrant, or Redis.
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(path: str, snippets: list[str], errors: list[str]) -> None:
    text = read(path)
    for snippet in snippets:
        if snippet not in text:
            errors.append(f"{path}: missing {snippet!r}")


def main() -> int:
    errors: list[str] = []

    require(
        "docker-compose.yml",
        [
            "${QDRANT_API_KEY:?QDRANT_API_KEY env zorunlu}",
            "${REDIS_PASSWORD:?REDIS_PASSWORD env zorunlu}",
            "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD env zorunlu}",
            "${JWT_SECRET:?JWT_SECRET env zorunlu}",
            "read_only: true",
            "no-new-privileges:true",
            "cap_drop:",
            "- ALL",
            "/tmp:size=512m,mode=1777",
            "VERIFY_STRICT: ${VERIFY_STRICT:-1}",
            "Qwen3.5-9B-UD-Q4_K_XL.gguf",
            "condition: service_healthy",
            "http://127.0.0.1:8000/health",
            "http://127.0.0.1:8080/health",
        ],
        errors,
    )

    require(
        ".env.example",
        [
            "QDRANT_API_KEY=",
            "JWT_SECRET=",
            "REDIS_PASSWORD=",
            "POSTGRES_PASSWORD=",
            "LLM_MODE=llamacpp_server",
            "LLAMA_MODEL_FILE=Qwen3.5-9B-UD-Q4_K_XL.gguf",
            "VERIFY_STRICT=1",
            "SECURITY_HSTS_ENABLED=1",
        ],
        errors,
    )

    require(
        "backend/Dockerfile",
        [
            "FROM python:3.11-slim AS builder",
            "FROM python:3.11-slim AS runtime",
            "tesseract-ocr-tur",
            "ffmpeg",
            "USER app",
            "HEALTHCHECK",
            "http://127.0.0.1:8000/health",
        ],
        errors,
    )

    require(
        "backend/.env.example",
        [
            "AUTH_ENABLED=1",
            "AUTH_PROVIDER=supabase",
            "SUPABASE_URL=https://<proje-ref>.supabase.co",
            "VERIFY_STRICT=1",
            "ALLOWED_ORIGINS=",
            "RATE_LIMIT_STORAGE_URI=",
        ],
        errors,
    )

    require(
        "backend/api/passwords.py",
        [
            "password_policy_issues",
            "_COMMON_COMPROMISED_PASSWORDS",
            "Şifre e-posta veya ad bilgisi içermemeli.",
        ],
        errors,
    )

    require(
        "frontend/src/lib/passwordPolicy.js",
        [
            "COMMON_COMPROMISED_PASSWORDS",
            "passwordPolicyIssues",
            "passwordPolicyIssuesWithBreachCheck",
            "api.pwnedpasswords.com/range",
            "Add-Padding",
            "assertPasswordPolicyWithBreachCheck",
        ],
        errors,
    )

    require(
        "frontend/.env.example",
        [
            "VITE_HIBP_PASSWORD_CHECK=1",
        ],
        errors,
    )

    require(
        "frontend/src/hooks/useAuth.js",
        [
            "assertPasswordPolicyWithBreachCheck(password, { email, name })",
            "supabase.auth.signUp",
        ],
        errors,
    )

    require(
        ".github/workflows/backend-ci.yml",
        [
            "docker build smoke",
            "BOOT SMOKE OK",
            "Trivy imaj",
            "eval.scorecard --check",
            "readiness-gates",
            "check_production_readiness.py",
            "check_live_integrations.py",
        ],
        errors,
    )

    require(
        "supabase/schema.sql",
        [
            "enable row level security",
            "grant usage on schema public to authenticated",
            "grant select, insert, update, delete on table public.conversations to authenticated",
            "revoke all on table public.conversations from public, anon, authenticated",
            "grant execute on function public.save_conversation(text, text, text, jsonb) to authenticated",
        ],
        errors,
    )

    require(
        "docs/CURRENT_STATUS.md",
        [
            "Production readiness",
            "Multimodal/training/live integration readiness",
            "check_production_readiness.py",
            "check_live_integrations.py",
        ],
        errors,
    )

    if errors:
        print("Production readiness check failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Production readiness check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
