"""2209-A başvurusu için görsel varlıklar (matplotlib): mimari diyagram, ön-sonuç
grafiği, Gantt zaman çizelgesi. Yüksek-DPI PNG üretir; docx'e gömülür."""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
ASSETS.mkdir(exist_ok=True)

# --- Akademik renk paleti (WCAG AA kontrast düzeltmeli, ECC a11y) ---
NAVY = "#1B3A5B"
TEAL = "#256E8E"   # koyulaştırıldı: beyaz yazı kontrastı 4.59→~5.4 (AA güvenli)
GOLD = "#C49A3A"   # canlı kalır; üstüne KOYU (INK) yazı kullanılır (beyaz 2.61 FAIL idi)
LIGHT = "#EEF4FA"
LIGHT2 = "#E3EDF6"
GREEN = "#2D6B43"  # koyulaştırıldı: beyaz yazı 4.02→6.37 (AA)
GREY = "#5B6B7B"
INK = "#1B2733"

# Arial varsa kullan (docx ile tutarlı)
for cand in ("Arial", "DejaVu Sans"):
    if any(cand in f.name for f in fm.fontManager.ttflist):
        plt.rcParams["font.family"] = cand
        break
plt.rcParams["font.size"] = 9


def _box(ax, x, y, w, h, text, face, edge, tcolor="white", fs=8.4, bold=True):
    box = FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0.012,rounding_size=0.03",
        linewidth=1.1, edgecolor=edge, facecolor=face, mutation_aspect=1,
    )
    ax.add_patch(box)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
            color=tcolor, fontsize=fs, fontweight="bold" if bold else "normal", wrap=True)


def _arrow(ax, x0, y0, x1, y1, color=NAVY):
    ax.add_patch(FancyArrowPatch(
        (x0, y0), (x1, y1), arrowstyle="-|>", mutation_scale=13,
        linewidth=1.6, color=color, shrinkA=2, shrinkB=2,
    ))


def architecture():
    fig, ax = plt.subplots(figsize=(7.4, 3.05), dpi=200)
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 6)
    ax.axis("off")

    # Üst sıra: ana hat
    row = 3.5
    h, w = 1.15, 2.05
    steps = [
        (0.2, "Vatandaş\nSorusu", GREY, GREY, "white"),
        (2.55, "PII Maskeleme\n(TCKN/telefon)", GOLD, GOLD, INK),
        (4.9, "RAG Getirim\nEmbedding+Qdrant\n+Yeniden Sıralama", TEAL, TEAL, "white"),
        (7.25, "Taslak Üretimi\n(LLM)", NAVY, NAVY, "white"),
        (9.6, "İddialara Ayırma\n+ Kaynak Eşleme", TEAL, TEAL, "white"),
        (11.95, "Doğrulama\nNLI + LettuceDetect", NAVY, NAVY, "white"),
    ]
    centers = []
    for x, t, fc, ec, tc in steps:
        _box(ax, x, row, w, h, t, fc, ec, tcolor=tc, fs=8.0)
        centers.append((x, x + w))
    for i in range(len(steps) - 1):
        _arrow(ax, centers[i][1], row + h / 2, centers[i + 1][0], row + h / 2)

    # Alt: nihai çıktı + ret yolu
    out_y = 1.15
    _box(ax, 9.6, out_y, w + 0.3, h, "Güvenli Cevap\nKaynaklı + Disclaimer", GREEN, GREEN, fs=8.0)
    _arrow(ax, 12.95, row, 11.0, out_y + h, color=GREEN)
    _box(ax, 7.0, out_y, w, h, "Güvenli Ret /\nEk Bilgi İste", "#B5482E", "#B5482E", fs=8.0)
    _arrow(ax, 12.0, row, 8.0, out_y + h, color="#B5482E")

    # Katman etiketleri
    ax.text(5.9, row + h + 0.5, "LOKAL (gizli)", ha="center", color=TEAL, fontsize=8, fontweight="bold")
    ax.text(8.27, row + h + 0.5, "BULUT/LOKAL", ha="center", color=NAVY, fontsize=8, fontweight="bold")
    ax.text(13.0, row + h + 0.5, "LOKAL (denetçi)", ha="center", color=NAVY, fontsize=8, fontweight="bold")

    ax.text(7, 5.62, "Şekil 2. Kaynak-temelli RAG + iddia-düzeyi doğrulama ajan hattı",
            ha="center", color=INK, fontsize=8.6, fontweight="bold")
    fig.tight_layout(pad=0.3)
    fig.savefig(ASSETS / "fig_architecture.png", dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def experiment_design():
    fig, ax = plt.subplots(figsize=(7.6, 3.0), dpi=300)
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 6)
    ax.axis("off")

    # Ortak soru seti
    _box(ax, 0.1, 2.1, 2.95, 1.65,
         "ORTAK SORU SETİ\n150–300 soru · 8 hukuk alanı\nkamuya açık mevzuat\n+ yargı kararları",
         NAVY, NAVY, "white", fs=7.2)
    # İki kol
    _box(ax, 4.45, 3.75, 3.35, 1.15, "KOL A — Doğrulama KAPALI\n(klasik RAG)", TEAL, TEAL, "white", fs=7.7)
    _box(ax, 4.45, 1.05, 3.35, 1.15, "KOL B — Doğrulama AÇIK\n(iddia-düzeyi NLI + kaynak eşleme)",
         GREEN, GREEN, "white", fs=7.4)
    # Ortak ölçütler (açık kutu, koyu yazı)
    _box(ax, 9.0, 2.05, 2.85, 1.75,
         "ORTAK ÖLÇÜTLER\nhalüsinasyon yakalama,\nyanlış ret, iddia-destek,\nkaynak doğruluğu,\ngecikme, maliyet",
         "#E3EDF6", NAVY, INK, fs=7.5)
    # İstatistik
    _box(ax, 12.15, 2.35, 1.75, 1.2,
         "EŞLEŞTİRİLMİŞ\nKARŞILAŞTIRMA\nMcNemar · Wilson GA\nCohen κ", GOLD, GOLD, INK, fs=7.0)

    _arrow(ax, 3.05, 3.0, 4.45, 4.3)   # soru → KOL A
    _arrow(ax, 3.05, 2.9, 4.45, 1.6)   # soru → KOL B
    _arrow(ax, 7.8, 4.3, 9.0, 3.2)     # KOL A → ölçüt
    _arrow(ax, 7.8, 1.6, 9.0, 2.6)     # KOL B → ölçüt
    _arrow(ax, 11.85, 2.95, 12.15, 2.95, color=GOLD)  # ölçüt → istatistik

    ax.text(3.6, 5.0, "aynı sorular\n(eşleştirilmiş)", ha="center", color=GREY, fontsize=7.2, style="italic")
    ax.text(7, 5.62, "Şekil 3. Kontrollü deney tasarımı: doğrulama KAPALI vs AÇIK, aynı soru setinde",
            ha="center", color=INK, fontsize=8.6, fontweight="bold")
    fig.tight_layout(pad=0.3)
    fig.savefig(ASSETS / "fig_experiment.png", dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def results():
    fig, ax = plt.subplots(figsize=(6.6, 2.55), dpi=200)
    labels = ["Alan@5\n(retrieval)", "MRR\n(retrieval)", "Halüsinasyon\nyakalama",
              "Uydurma eşik\nF1"]
    vals = [97.3, 87.9, 100.0, 97.67]
    colors = [TEAL, TEAL, NAVY, GOLD]
    bars = ax.bar(labels, vals, color=colors, width=0.62, edgecolor="white", linewidth=0.6, zorder=3)
    ax.set_ylim(0, 112)
    ax.set_ylabel("Yüzde / 100 üzerinden", fontsize=8.2, color=INK)
    ax.grid(axis="y", color="#D7E0EA", linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#AEBBC8")
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 2.4, f"{v:g}", ha="center",
                va="bottom", fontsize=8.4, fontweight="bold", color=INK)
    ax.tick_params(labelsize=7.6, length=0)
    ax.set_title("Şekil 1. Ön çalışma ölçümleri (159.362 vektör; 186 retrieval, 104 risk, 46 eşik vakası)",
                 fontsize=8.4, fontweight="bold", color=INK, pad=8)
    fig.tight_layout(pad=0.3)
    fig.savefig(ASSETS / "fig_results.png", dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def gantt():
    fig, ax = plt.subplots(figsize=(7.8, 2.95), dpi=300)
    tasks = [
        ("İP1 · Kapsam, etik, veri şeması", 1, 1, GOLD),
        ("İP2 · Korpus + değerlendirme seti", 2, 2, TEAL),
        ("İP3 · Baseline & doğrulamalı RAG deneyleri", 4, 2, NAVY),
        ("İP4 · İnsan değerlendirmesi & hata analizi", 6, 2, TEAL),
        ("İP5 · Maliyet/gecikme + opsiyonel Qwen", 8, 2, GREY),
        ("İP6 · Rapor, sunum, tekrar-üretilebilir ekler", 10, 3, GREEN),
    ]
    n = len(tasks)
    names = []
    for i, (name, start, dur, color) in enumerate(tasks):
        y = n - 1 - i
        ax.barh(y, dur, left=start, height=0.62, color=color, edgecolor="white",
                linewidth=0.9, zorder=3)
        tc = INK if color == GOLD else "white"
        # Bar İÇİNE sadece kısa süre etiketi (taşma/kesilme YOK)
        ax.text(start + dur / 2, y, f"{dur} ay", ha="center", va="center", color=tc,
                fontsize=7.4, fontweight="bold")
        names.append(name)
    # Tam iş-paketi adları SOL EKSENDE (kesilmez)
    ax.set_yticks(range(n))
    ax.set_yticklabels(names[::-1], fontsize=7.8, color=INK)
    ax.set_ylim(-0.6, n - 0.4)
    ax.set_xlim(1, 13)
    ax.set_xticks(range(1, 14))
    ax.set_xticklabels([f"Ay {m}" for m in range(1, 13)] + [""], fontsize=7.4)
    ax.set_xlabel("Proje takvimi (12 ay)", fontsize=8.2, color=INK)
    ax.grid(axis="x", color="#D7E0EA", linewidth=0.7, zorder=0)
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", length=0)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color("#AEBBC8")
    ax.set_title("Şekil 4. İş paketleri – zaman çizelgesi (Gantt)",
                 fontsize=8.4, fontweight="bold", color=INK, pad=8)
    fig.tight_layout(pad=0.3)
    fig.savefig(ASSETS / "fig_gantt.png", dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    results()
    architecture()
    experiment_design()
    gantt()
    print("figs ->", ASSETS)
