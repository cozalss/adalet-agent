/* ErrorBoundary — çöken bileşenin tüm ağacı beyaz-ekrana çevirmesini önler (denetim #8). */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ErrorBoundary } from "./ErrorBoundary.jsx";

function Boom() {
  throw new Error("bilerek patlat");
}

describe("ErrorBoundary", () => {
  it("çöken çocuğu yakalar ve kurtarma UI'ı gösterir (beyaz ekran yok)", () => {
    // React yakalanan hatayı console.error'a basar — testi gürültüden arındır.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.getByText(/Beklenmeyen bir hata/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /yenile/i })).toBeTruthy();
    spy.mockRestore();
  });

  it("hata yokken çocukları normal render eder", () => {
    render(
      <ErrorBoundary>
        <div>içerik burada</div>
      </ErrorBoundary>,
    );
    expect(screen.getByText("içerik burada")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("getDerivedStateFromError hata state'i döndürür", () => {
    expect(ErrorBoundary.getDerivedStateFromError(new Error("x"))).toEqual({ hasError: true });
  });
});
