/* ADALET kullanıcı avatarı — isimden türeyen zarif gradient + baş harf (gem hissi).
   Dekoratif (ad metni yanında gösterilir) → aria-hidden. lib/avatar.js deterministik. */
import React from "react";
import { avatarSeed, avatarInitial, avatarStyle } from "../lib/avatar.js";

/**
 * @param {{ user?: object, prefs?: object, size?: number, className?: string }} props
 */
export function Avatar({ user, prefs, size = 30, className = "" }) {
  const seed = avatarSeed(user, prefs);
  return (
    <span
      className={`adl-avatar ${className}`.trim()}
      style={{
        width: size,
        height: size,
        flex: `0 0 ${size}px`,
        fontSize: Math.round(size * 0.42),
        ...avatarStyle(seed),
      }}
      aria-hidden="true"
    >
      {avatarInitial(seed)}
    </span>
  );
}
