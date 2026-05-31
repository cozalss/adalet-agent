/* ADALET sidebar — gerçek sohbet geçmişi listesi (kalıcı).
   "Bu oturum / saklanmaz" boş-durumunun yerine geçer. */
import React from "react";
import { Icon } from "./icons.jsx";
import { relDate } from "./historyPanels.jsx";

export function ConversationList({ conversations, activeId, onSelect, onDelete }) {
  if (!conversations.length) {
    return (
      <p className="sb-empty-note">
        <Icon.book style={{ width: 13, height: 13 }} />
        Sohbet geçmişiniz burada görünecek. İlk sorunuzu sorun.
      </p>
    );
  }
  return (
    <div className="sb-conv-list">
      {conversations.map((c) => (
        <div className={"sb-conv" + (c.id === activeId ? " active" : "")} key={c.id}>
          <button className="sb-conv-main" onClick={() => onSelect(c)} title={c.title}>
            <span className="sb-conv-title">{c.title}</span>
            <span className="sb-conv-date">{relDate(c.updatedAt)}</span>
          </button>
          <button
            className="sb-conv-del" onClick={(e) => { e.stopPropagation(); onDelete(c.id); }}
            aria-label="Sohbeti sil" title="Sohbeti sil"
          ><Icon.close /></button>
        </div>
      ))}
    </div>
  );
}
