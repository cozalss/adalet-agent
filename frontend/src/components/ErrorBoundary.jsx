import React from "react";

/* Üst-düzey hata sınırı (denetim #8): bir bileşen render sırasında çökerse tüm React
   ağacının beyaz ekrana dönmesini önler. Hukuki içerik göstermez — sakin bir kurtarma
   mesajı + "Sayfayı yenile". Hata teknik olarak konsola loglanır (kişisel veri yok). */
export class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error, info) {
    // Sessiz beyaz-ekran yerine gözlemlenebilirlik: yalnız teknik hata + component stack.
    if (typeof console !== "undefined") {
      console.error("ErrorBoundary yakaladı:", error, info?.componentStack);
    }
  }

  handleReload = () => {
    if (typeof window !== "undefined" && window.location) window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="error-boundary" role="alert" data-theme="warm">
          <h2>Beklenmeyen bir hata oluştu</h2>
          <p>
            Uygulama bu işlemi tamamlayamadı. Sayfayı yenileyip tekrar deneyebilirsiniz;
            sorun sürerse bir süre sonra yeniden deneyin.
          </p>
          <button className="btn primary" type="button" onClick={this.handleReload}>
            Sayfayı yenile
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
