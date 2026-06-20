/* UserMenu — hesap menüsü açılış, içerik zenginliği ve roving klavye gezinme
   (a11y: APG menu button sözleşmesi) testleri. */
import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { UserMenu } from "./UserMenu.jsx";

const basePrefs = {
  displayName: "", textScale: "normal", reduceMotion: false,
  highContrast: false, preferredDomains: [],
};
const user = { name: "Ayşe Yılmaz", email: "ayse@example.com" };

function renderMenu(extra = {}) {
  return render(
    <UserMenu
      prefs={basePrefs} setPref={() => {}} toggleDomain={() => {}}
      onClearSession={() => {}} onAsk={() => {}} showToast={() => {}}
      user={user} onLogout={() => {}} {...extra}
    />
  );
}

function openMenu() {
  fireEvent.click(screen.getByRole("button", { name: /hesap menüsünü aç/i }));
  return screen.getByRole("menu", { name: /hesap menüsü/i });
}

describe("UserMenu", () => {
  it("açılınca güven rozetleri + footer hukuki uyarısı görünür", () => {
    renderMenu();
    openMenu();
    expect(screen.getByText("7 Ajan")).toBeTruthy();
    expect(screen.getByText("Sıfır Uydurma")).toBeTruthy();
    expect(screen.getByText("Açık Kaynak")).toBeTruthy();
    expect(screen.getByText(/hukuki tavsiye değildir/i)).toBeTruthy();
  });

  it("gruplar role=group + erişilebilir ad ile etiketli", () => {
    renderMenu();
    openMenu();
    expect(screen.getByRole("group", { name: "Bu asistanı anla" })).toBeTruthy();
    expect(screen.getByRole("group", { name: "Oturum yönetimi" })).toBeTruthy();
  });

  it("kimlik kartının erişilebilir adı 'profili düzenle' içerir", () => {
    renderMenu();
    openMenu();
    expect(screen.getByRole("menuitem", { name: /Ayşe Yılmaz — profili düzenle/i })).toBeTruthy();
  });

  it("uzun ad/e-posta düzeni bozmadan render olur (taşma CSS ellipsis ile kırpılır)", () => {
    const longUser = {
      name: "Çoooook Uzun Bir Görünen İsim Buraya Yazıldı",
      email: "cooook.uzun.eposta.adresi@cooook-uzun-bir-alan-adi.example.com",
    };
    renderMenu({ user: longUser });
    const menu = openMenu();
    expect(within(menu).getByRole("menuitem", { name: /Çoooook Uzun Bir Görünen İsim/i })).toBeTruthy();
    expect(menu.textContent).toContain("cooook.uzun.eposta.adresi");
  });

  it("ArrowDown/ArrowUp/Home/End roving gezinme döngüsel çalışır", () => {
    renderMenu();
    const menu = openMenu();
    const items = within(menu).getAllByRole("menuitem");
    expect(items.length).toBeGreaterThan(3);

    items[0].focus();
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(document.activeElement).toBe(items[1]);

    items[0].focus();
    fireEvent.keyDown(menu, { key: "ArrowUp" }); // baştan yukarı → sona sar
    expect(document.activeElement).toBe(items[items.length - 1]);

    fireEvent.keyDown(menu, { key: "Home" });
    expect(document.activeElement).toBe(items[0]);

    fireEvent.keyDown(menu, { key: "End" });
    expect(document.activeElement).toBe(items[items.length - 1]);
  });
});
