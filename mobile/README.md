# Mobile

Flutter 3.x ile iOS ve Android için tek kod tabanlı uygulama.

## Sorumluluklar

- Yazılı + sesli + kamera çoklu giriş
- Whisper-TR ile lokal STT
- Coqui TTS ile cevap okuma
- Belge fotoğrafı → backend OCR'a yolla
- Offline taslak kaydetme
- Erişilebilirlik (büyük yazı, ekran okuyucu)

## Çalıştır

```bash
flutter pub get
flutter run                  # iOS Simulator / Android Emulator
flutter run -d chrome        # Web preview (debug)
```

## Stack

- Flutter 3.x (Dart)
- Riverpod (state management)
- `record` (ses kaydı)
- `camera` + `image_picker` (belge fotoğrafı)
- `dio` (HTTP client)
- `flutter_secure_storage` (token)

## Test

```bash
flutter test
flutter test integration_test
```

## Yapılacaklar

- [ ] Flutter projesi başlat (`flutter create .`)
- [ ] Riverpod state yapısı
- [ ] Chat ekranı (mesaj balonları)
- [ ] Ses kayıt + backend STT
- [ ] Kamera + backend OCR
- [ ] Erişilebilirlik testleri
